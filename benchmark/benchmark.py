from __future__ import print_function
try:
    from ompl import util as ou
    from ompl import base as ob
    from ompl import geometric as og
    from ompl import tools as ot
except ImportError:
    # if the ompl module is not in the PYTHONPATH assume it is installed in a
    # subdirectory of the parent directory called "py-bindings."
    from os.path import abspath, dirname, join
    import sys
    sys.path.insert(
        0, join(dirname(dirname(dirname(abspath(__file__)))), 'py-bindings'))
    from ompl import util as ou
    from ompl import base as ob
    from ompl import geometric as og
    from ompl import tools as ot
import datetime
import pandas as pd
import os, sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.prepare_results import *

def addSpaceOption(parser):
    parser.add_argument("-s", "--space", default="PJ",
                        choices=["PJ", "AT", "TB"],
                        help="""Choose which constraint handling methodology to use. One of:
        PJ - Projection (Default)
        AT - Atlas
        TB - Tangent Bundle.""")


def addPlannerOption(parser):
    parser.add_argument("-p", "--planner", default="RRTConnect",
                        help="Comma-separated list of which motion planner to use (multiple if "
                        "benchmarking, one if planning).\n Choose from, e.g.:\n"
                        "RRT (Default), RRTConnect, RRTstar, "
                        "EST, BiEST, ProjEST, "
                        "BITstar, "
                        "PRM, SPARS, "
                        "KPIECE1, BKPIECE1.")


def addConstrainedOptions(parser):
    group = parser.add_argument_group("Constrained planning options")
    group.add_argument("-d", "--delta", type=float, default=ob.CONSTRAINED_STATE_SPACE_DELTA,
                    help="Step-size for discrete geodesic on manifold.")
    group.add_argument("--lambda", type=float, dest="lambda_", metavar="LAMBDA",
                    default=ob.CONSTRAINED_STATE_SPACE_LAMBDA*2,
                    help="Maximum `wandering` allowed during atlas traversal. Must be greater "
                    "than 1.")
    group.add_argument("--tolerance", type=float, default=0.01,
                    help="Constraint satisfaction tolerance.")
    group.add_argument("--time", type=float, default=60.,
                    help="Planning time allowed.")
    group.add_argument("--tries", type=int, default=ob.CONSTRAINT_PROJECTION_MAX_ITERATIONS,
                    help="Maximum number sample tries per sample.")
    group.add_argument("-r", "--range", type=float, default=0.,
                    help="Planner `range` value for planners that support this parameter. "
                    "Automatically determined otherwise (when 0).")

def list2vec(l):
    ret = ou.vectorDouble()
    for e in l:
        ret.append(e)
    return ret

def clearSpaceAndPlanner(planner):
    planner.getSpaceInformation().getStateSpace().clear()
    planner.clear()


def addAtlasOptions(parser):
    group = parser.add_argument_group("Atlas options")
    group.add_argument("--epsilon", type=float, default=ob.ATLAS_STATE_SPACE_EPSILON,
                    help="Maximum distance from an atlas chart to the manifold. Must be "
                    "positive.")
    group.add_argument("--rho", type=float, default=ob.CONSTRAINED_STATE_SPACE_DELTA *
                    ob.ATLAS_STATE_SPACE_RHO_MULTIPLIER,
                    help="Maximum radius for an atlas chart. Must be positive.")
    group.add_argument("--exploration", type=float, default=ob.ATLAS_STATE_SPACE_EXPLORATION,
                    help="Value in [0, 1] which tunes balance of refinement and exploration in "
                    "atlas sampling.")
    group.add_argument("--alpha", type=float, default=ob.ATLAS_STATE_SPACE_ALPHA,
                    help="Maximum angle between an atlas chart and the manifold. Must be in "
                    "[0, PI/2].")
    group.add_argument("--bias", action="store_true",
                    help="Sets whether the atlas should use frontier-biased chart sampling "
                    "rather than uniform.")
    group.add_argument("--no-separate", action="store_true",
                    help="Sets that the atlas should not compute chart separating halfspaces.")
    group.add_argument("--charts", type=int, default=ob.ATLAS_STATE_SPACE_MAX_CHARTS_PER_EXTENSION,
                    help="Maximum number of atlas charts that can be generated during one "
                    "manifold traversal.")


class ConstrainedProblem(object):

    def __init__(self, spaceType, space, constraint, options):
        self.spaceType = spaceType
        self.space = space
        self.constraint = constraint
        self.constraint.setTolerance(0.0075)
        self.constraint.setMaxIterations(options.tries)
        self.options = options
        self.bench = None
        self.request = None
        self.pp = None
        self.results = pd.DataFrame(columns=['std_deviation', 'time', 'succes'])
        # self.results = pd.concat([self.results, pd.DataFrame({'deviation': [1]})])
        print(self.results)

        if spaceType == "PJ":
            ou.OMPL_INFORM("Using Projection-Based State Space!")
            self.css = ob.ProjectedStateSpace(space, constraint)
            self.csi = ob.ConstrainedSpaceInformation(self.css)
        elif spaceType == "AT":
            ou.OMPL_INFORM("Using Atlas-Based State Space!")
            self.css = ob.AtlasStateSpace(space, constraint)
            self.csi = ob.ConstrainedSpaceInformation(self.css)
        elif spaceType == "TB":
            ou.OMPL_INFORM("Using Tangent Bundle-Based State Space!")
            self.css = ob.TangentBundleStateSpace(space, constraint)
            self.csi = ob.TangentBundleSpaceInformation(self.css)

        self.css.setup()
        self.css.setDelta(options.delta)
        self.css.setLambda(options.lambda_)
        if not spaceType == "PJ":
            self.css.setExploration(options.exploration)
            self.css.setEpsilon(options.epsilon)
            self.css.setRho(options.rho)
            self.css.setAlpha(options.alpha)
            self.css.setMaxChartsPerExtension(options.charts)
            if options.bias:
                self.css.setBiasFunction(lambda c, atlas=self.css:
                                        atlas.getChartCount() - c.getNeighborCount() + 1.)
            if spaceType == "AT":
                self.css.setSeparated(not options.no_separate)
            self.css.setup()
        self.ss = og.SimpleSetup(self.csi)

    def setStartAndGoalStates(self, start, goal):
        # Create start and goal states
        if self.spaceType == "AT" or self.spaceType == "TB":
            self.css.anchorChart(start())
            self.css.anchorChart(goal())

        # Setup problem
        self.ss.setStartAndGoalStates(start, goal)

    def getPlanner(self, plannerName, projectionName=None):
        planner = eval('og.%s(self.csi)' % plannerName)
        try:
            if self.options.range == 0:
                if not self.spaceType == "PJ":
                    planner.setRange(self.css.getRho_s())
            else:
                planner.setRange(self.options.range)
        except:
            pass
        try:
            if projectionName:
                planner.setProjectionEvaluator(projectionName)
        except:
            pass
        return planner

    def setPlanner(self, plannerName, projectionName=None):
        self.pp = self.getPlanner(plannerName, projectionName)
        self.ss.setPlanner(self.pp)

    def solveOnce(self, output=True, name="ompl"):
        self.ss.setup()
        stat = self.ss.solve(self.options.time)
        if stat:
            # Get solution and validate
            path = self.ss.getSolutionPath()
            print(path)
            if not path.check():
                ou.OMPL_WARN("Path fails check!")

            if stat == ob.PlannerStatus.APPROXIMATE_SOLUTION:
                ou.OMPL_WARN("Solution is approximate.")

            # Simplify solution and validate simplified solution path.
            ou.OMPL_INFORM("Simplifying solution...")
            self.ss.simplifySolution(40.)

            simplePath = self.ss.getSolutionPath()
            ou.OMPL_INFORM("Simplified Path Length: %.3f -> %.3f" %
                        (path.length(), simplePath.length()))

            if not simplePath.check():
                ou.OMPL_WARN("Simplified path fails check!")

            # Interpolate and validate interpolated solution path.
            ou.OMPL_INFORM("Interpolating path...")
            path.interpolate(1000)
            print(path)

            if not path.check():
                ou.OMPL_WARN("Interpolated simplified path fails check!")

            ou.OMPL_INFORM("Interpolating simplified path...")
            simplePath.interpolate(1000)

            if not simplePath.check():
                ou.OMPL_WARN("Interpolated simplified path fails check!")
                simplePath = path

            if output:
                ou.OMPL_INFORM("Dumping path to `%s_path.txt`." % name)
                with open('logs/%s_path.txt' % name, 'w') as pathfile:
                    print(path.printAsMatrix(), file=pathfile)

                ou.OMPL_INFORM(
                    "Dumping simplified path to `%s_simplepath.txt`." % name)
                with open("logs/%s_simplepath.txt" % name, 'w') as simplepathfile:
                    print(simplePath.printAsMatrix(), file=simplepathfile)
                
        else:
            ou.OMPL_WARN("No solution found.")
        
        if output:
            if stat:
                states = [[x[i] for i in range(self.css.getAmbientDimension())] for x in simplePath.getStates()]
                deviation = calc_constraint_deviation(np.array(states), self.constraint)
            else:
                deviation = None
            self.results = pd.concat([self.results, pd.DataFrame({'std_deviation': [deviation], 'time': [self.ss.getLastPlanComputationTime()], 'succes': [1.0 if bool(stat) else 0.0]})])
        print(self.results)

        return stat

    def setupBenchmark(self, planners, problem):
        self.bench = ot.Benchmark(self.ss, problem)

        self.bench.addExperimentParameter(
            "n", "INTEGER", str(self.constraint.getAmbientDimension()))
        self.bench.addExperimentParameter(
            "k", "INTEGER", str(self.constraint.getManifoldDimension()))
        self.bench.addExperimentParameter(
            "n - k", "INTEGER", str(self.constraint.getCoDimension()))
        self.bench.addExperimentParameter("space", "INTEGER", self.spaceType)

        self.request = ot.Benchmark.Request()
        self.request.maxTime = self.options.time
        self.request.maxMem = 1e9
        self.request.runCount = 3
        self.request.timeBetweenUpdates = 0.1
        self.request.saveConsoleOutput = False
        for planner in planners:
            self.bench.addPlanner(self.getPlanner(planner, problem))

        self.bench.setPreRunEvent(ot.PreSetupEvent(clearSpaceAndPlanner))

    def runBenchmark(self):
        self.bench.benchmark(self.request)
        filename = str(datetime.datetime.now()) + '_' + \
            self.bench.getExperimentName() + '_' + self.spaceType
        self.bench.saveResultsToFile(filename)

    def atlasStats(self):
        # For atlas types, output information about size of atlas and amount of
        # space explored
        if self.spaceType == "AT" or self.spaceType == "TB":
            ou.OMPL_INFORM("Atlas has %d charts" % self.css.getChartCount())
            if self.spaceType == "AT":
                ou.OMPL_INFORM("Atlas is approximately %.3f%% open" %
                            self.css.estimateFrontierPercent())

    def dumpGraph(self, name):
        ou.OMPL_INFORM("Dumping planner graph to `%s_graph.graphml`." % name)
        data = ob.PlannerData(self.csi)
        self.pp.getPlannerData(data)

        with open("logs/%s_graph.graphml" % name, "w") as graphfile:
            print(data.printGraphML(), file=graphfile)

        if self.spaceType == "AT" or self.spaceType == "TB":
            ou.OMPL_INFORM("Dumping atlas to `%s_atlas.ply`." % name)
            with open("logs/%s_atlas.ply" % name, "w") as atlasfile:
                print(self.css.printPLY(), file=atlasfile)