from __future__ import print_function
import argparse
import math
import numpy as np
import sys, os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.benchmark import *
import mujoco
from agents.dummy import DummyAgent

from tasks.air_hockey_challenge.air_hockey_challenge.framework.air_hockey_challenge_wrapper import AirHockeyChallengeWrapper
from tasks.air_hockey_challenge.air_hockey_challenge.framework import AgentBase
from tasks.air_hockey_challenge.air_hockey_challenge.utils.kinematics import forward_kinematics, inverse_kinematics, jacobian, link_to_xml_name

from constraints.airhockey_ompl_constraint import AirHockeyCircleConstraint



def airhockey_planning_once(cp, plannername, output):
    cp.setPlanner(plannername, "airhockey")

    # Solve the problem
    stat = cp.solveOnce(output, "airhockey")

    if output:
        ou.OMPL_INFORM("Dumping problem information to `airhockey_info.txt`.")
        with open("logs/airhockey_info.txt", "w") as infofile:
            print(cp.spaceType, file=infofile)
    
    if output:
        ou.OMPL_INFORM("Dumping planning quality criterios `airhockey_criterios.txt`.")
        print(cp.results.mean(axis = 0, skipna=True))

    cp.atlasStats()
    if output:
        cp.dumpGraph("airhockey")
    return stat


def airhockey_planning_bench(cp, planners):
    cp.setupBenchmark(planners, "airhockey")
    cp.runBenchmark()


def airhockey_planning(options):
    env = AirHockeyChallengeWrapper(env="3dof-hit", action_type="position-velocity",
                                    interpolation_order=3, debug=False)
    agents = DummyAgent(env.env_info, 5)
    obs = env.reset()
    agents.episode_start()

    # Calculate current and finish position for circle constraint
    qs = agents.get_joint_pos(obs)
    current_ee_pose = forward_kinematics(
        env.env_info['robot']['robot_model'],
        env.env_info['robot']['robot_data'],
        qs
    )
    qf_res, qf = inverse_kinematics(
        env.env_info['robot']['robot_model'],
        env.env_info['robot']['robot_data'],
        current_ee_pose[0] + np.array([0.2, 0, 0]), initial_q=qs
    )
    print(qs, qf)
    if not qf_res:
        raise("Cannot solve inverse kinematic problem for end point")
    
    # Create the ambient space state space for the problem.
    rvss = ob.RealVectorStateSpace(env.env_info['robot']['n_joints'])     
    bounds = ob.RealVectorBounds(env.env_info['robot']['n_joints'])
    lb = env.env_info['robot']['joint_pos_limit'][0,:]
    ub = env.env_info['robot']['joint_pos_limit'][1,:]
    for i in range(env.env_info['robot']['n_joints']):
        bounds.setLow(i, lb[i])
        bounds.setHigh(i, ub[i])
    rvss.setBounds(bounds)

    # Create our constraint.
    constraint = AirHockeyCircleConstraint(
        env.env_info['robot']['n_joints'],
        env.env_info['robot']['robot_model'],
        env.env_info['robot']['robot_data'],
        current_ee_pose[0] + np.array([0.1, 0, 0]), 0.1
    )

    cp = ConstrainedProblem(options.space, rvss, constraint, options)

    cp.ss.clear()
    start = ob.State(cp.css)
    goal = ob.State(cp.css)
    for i in range(env.env_info['robot']['n_joints']):
        start[i] = qs[i]
        goal[i] = qf[i]
    cp.setStartAndGoalStates(start, goal)
    # cp.ss.setStateValidityChecker(ob.StateValidityCheckerFn(obstacles))

    planners = options.planner.split(",")
    if options.bench:
        for i in range(0, 100):
            airhockey_planning_once(cp, planners[0], options.output)
    else:
        airhockey_planning_once(cp, planners[0], options.output)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", action="store_true",
                        help="Dump found solution path (if one exists) in plain text and planning "
                        "graph in GraphML to `airhockey_path.txt` and `airhockey_graph.graphml` "
                        "respectively.")
    parser.add_argument("--bench", action="store_true",
                        help="Do benchmarking on provided planner list.")
    addSpaceOption(parser)
    addPlannerOption(parser)
    addConstrainedOptions(parser)
    addAtlasOptions(parser)

    airhockey_planning(parser.parse_args())