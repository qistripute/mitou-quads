from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np
from numpy.typing import NDArray

from models.amp_sim.sampler import init_normal_state, sampling_grover_oracle
from models.parameters import CMAHyperParam, CMAParam, QuadsParam, QuadsHyperParam, update_quads_params, get_normal_samples


def get_samples_grover(func, quads_param: QuadsParam, config):
    accepted = []
    accepted_val = []
    mean = quads_param.cma_param.mean
    cov = quads_param.cma_param.cov * quads_param.cma_param.step_size ** 2
    threshold = quads_param.threshold

    n_eval = 0
    for _ in range(config["n_samples"]):
        initial_state = init_normal_state(
            config["n_digits"], mean, cov, config["n_dim"])
        x, y, eval_num = sampling_grover_oracle(
            func, mean, cov, config["n_digits"], config["n_dim"], threshold, optimal_amplify_num=config["optimal_amplify_num"], initial_state=initial_state, oracle_eval_limit=config["eval_limit_one_sample"])

        n_eval += eval_num

        accepted.append(x)
        accepted_val.append(y)

    return np.array(accepted), np.array(accepted_val).squeeze(), n_eval


def optimal_amplify_num(p):
    return np.arccos(np.sqrt(p)) / 2 / np.arcsin(np.sqrt(p))

def get_samples_classical(func, quads_param:QuadsParam, config):
    n_sampled = 0
    n_eval = 0
    accepted = np.empty((0, config["n_dim"]))
    accepted_val = np.empty(0)

    diagDD, B = np.linalg.eigh(quads_param.cma_param.cov)
    diagD = np.sqrt(diagDD)
    BD = np.matmul(B, np.diag(diagD))
    n_samples = config["n_samples"]
    while n_sampled < n_samples:
        n_parallel = 100
        sample = get_normal_samples(quads_param.cma_param, config["n_dim"], n_parallel, BD=BD)

        func_val = func(sample)
        accept_flag = func_val < quads_param.threshold
        accept_num = np.count_nonzero(accept_flag)

        if accept_num + n_sampled >= n_samples:
            n_eval += np.sort(np.where(accept_flag)[0])[n_samples-n_sampled-1]+1
            accepted = np.concatenate([accepted, sample[accept_flag][:n_samples-n_sampled]])
            accepted_val = np.concatenate([accepted_val, func_val[accept_flag][:n_samples-n_sampled]])
            break
            
        n_eval += n_parallel
        n_sampled += accept_num
        accepted = np.concatenate([accepted, sample[accept_flag]])
        accepted_val = np.concatenate([accepted_val, func_val[accept_flag]])


        if n_eval > config["eval_limit_one_sample"]:
            raise TimeoutError

    p = n_samples / n_eval
    n_eval_estimated = (optimal_amplify_num(p) + 1) * n_samples

    return accepted, accepted_val, n_eval_estimated


def run_quads(
    func: Callable[[NDArray], NDArray],
    init_param: QuadsParam,
    config,
    verbose=False
):

    hp = QuadsHyperParam(quantile=config["quantile"], smoothing_th=config["smoothing_th"], 
                         cma_hyperparam=CMAHyperParam(config["n_dim"], config["n_samples"], ))

    quads_param = init_param
    eval_num_hist = []
    param_hist = [init_param]
    min_func_hist = []
    dist_target_hist = []

    min_val = np.inf

    for i in range(config["max_iter"]):
        # しきい値未満のサンプルを得る
        try:
            if config["sampler_type"] == "quantum":
                accepted, accepted_val, n_eval = get_samples_grover(
                    func, quads_param, config)
            elif config["sampler_type"] == "classical":
                accepted, accepted_val, n_eval = get_samples_classical(
                    func, quads_param, config)
            else:
                raise NotImplementedError

        except TimeoutError:
            break

        # パラメーター更新
        quads_param = update_quads_params(
            accepted, accepted_val, i, quads_param, hp)

        # 履歴の保存
        min_val = min(min_val, np.min(accepted_val))
        dist_target = np.min(np.linalg.norm(
            accepted - config["target"][None], axis=1))
        param_hist.append(quads_param)
        min_func_hist.append(min_val)
        dist_target_hist.append(dist_target)
        eval_num_hist.append(n_eval)

        if verbose:
            print("-------")
            print("accepted", accepted)
            print("accepted_val", accepted_val)
            print("iter: ", i)
            print("updated mu: ", quads_param.cma_param.mean)
            print("cov: ", quads_param.cma_param.cov)
            print("step_size: ", quads_param.cma_param.step_size)
            print("threshold: ", quads_param.threshold)
            print("eval_num: ", eval_num_hist[-1])
            print("--------")

        if dist_target < config["terminate_eps"] or quads_param.cma_param.step_size < config["terminate_step_size"]:
            break

    print("total_eval_num: ", sum(eval_num_hist))
    return quads_param, (np.array(min_func_hist),np.array(eval_num_hist), np.array(dist_target_hist), param_hist )


if __name__ == "__main__":
    init_threshold = 1.
    init_mean, init_cov = np.array([0.2, 0.8]), np.array([[1, 0], [0, 1]])
    init_step_size = 1.
    quads_param = QuadsParam(
        init_threshold, CMAParam(init_mean, init_cov, init_step_size ))
    target = np.array([0.8, 0.2])

    config = {
        "sampler_type": "classical",
        "n_dim": 2,
        "n_digits": 8,
        "max_iter": 30,
        "n_samples": 3,
        "terminate_step_size": 0.001,
        "terminate_eps": 0.001,
        "optimal_amplify_num": False,
        "quantile": 0.1,
        "smoothing_th": 0.5,
        "target": target,
        "eval_limit_one_sample": 10000
    }

    def func(x):
        return (20 + np.sum(
            100 * (x - target[None, :]) ** 2 -
            10 * np.cos(2 * np.pi * 10 * (x - target[None, :])), axis=-1)) / 40

    result_param, (param_hist, eval_num_hist, min_func_hist) = run_quads(
        func, quads_param, config, verbose=True)
