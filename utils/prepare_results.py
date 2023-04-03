from ompl import base as ob
from ompl import geometric as og
import numpy as np

from scipy.interpolate import CubicSpline
import matplotlib.pyplot as plt

def calc_constraint_deviation(path: np.ndarray, constraint: ob.Constraint) -> float:
    deviations_list = []
    for i in range(0, path.shape[0]):
        deviation = np.zeros(1)
        constraint.function(path[i, :], deviation)
        deviations_list.append(np.copy(deviation[0]))
    return np.std(np.array(deviations_list))

def plot_path(path: np.ndarray, true_path: np.ndarray):
    cs = CubicSpline(np.arange(0, path.shape[0]), path)
    xs = np.arange(0, path.shape[0]-1, 0.1)

    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.plot(path[:, 0], path[:, 1], 'o', label='data')
    ax.plot(true_path[:, 0], true_path[:, 1], label='true')
    ax.plot(cs(xs)[:, 0], cs(xs)[:, 1], label='spline')
    ax.axes.set_aspect('equal') 
    ax.legend(loc='center')
    plt.show()