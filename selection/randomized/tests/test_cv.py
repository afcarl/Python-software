import functools

import numpy as np
from scipy.stats import norm as ndist
import matplotlib.pyplot as plt

import regreg.api as rr
from selection.api import (randomization,
                           glm_group_lasso,
                           multiple_queries,
                           glm_target)
import selection.api as sel
from selection.tests.instance import (gaussian_instance,
                                      logistic_instance)
from selection.randomized.glm import (pairs_bootstrap_glm,
                                      glm_nonparametric_bootstrap)
from selection.algorithms.lasso import (glm_sandwich_estimator,
                                        lasso)
from selection.constraints.affine import (constraints,
                                          stack)
from selection.randomized.query import naive_confidence_intervals

import selection.tests.reports as reports
from selection.tests.flags import SMALL_SAMPLES, SET_SEED
from selection.tests.decorators import wait_for_return_value, set_seed_iftrue, set_sampling_params_iftrue, register_report
from selection.randomized.cv_view import CV_view


@register_report(['truth', 'cover', 'naive_cover', 'active'])
@set_seed_iftrue(SET_SEED)
@set_sampling_params_iftrue(SMALL_SAMPLES, burnin=10, ndraw=10)
@wait_for_return_value()
def test_cv(n=300, p=20, s=10, snr=5, K=5, rho=0,
             randomizer='gaussian',
             randomizer_scale = 0.5,
             loss = 'gaussian',
             intervals = 'old',
             bootstrap = False,
             marginalize_subgrad = True,
             ndraw = 10000,
             burnin = 2000):

    if randomizer == 'laplace':
        randomizer = randomization.laplace((p,), scale=randomizer_scale)
    elif randomizer == 'gaussian':
        randomizer = randomization.isotropic_gaussian((p,),randomizer_scale)
    elif randomizer == 'logistic':
        randomizer = randomization.logistic((p,), scale=randomizer_scale)

    if loss == "gaussian":
        X, y, beta, nonzero, sigma = gaussian_instance(n=n, p=p, s=s, rho=rho, snr=snr, sigma=1)
        glm_loss = rr.glm.gaussian(X, y)
    elif loss == "logistic":
        X, y, beta, _ = logistic_instance(n=n, p=p, s=s, rho=rho, snr=snr)
        glm_loss = rr.glm.logistic(X, y)

    # view 1
    cv = CV_view(glm_loss)
    cv.solve()
    #cv.condition_on_opt_state()

    #L = lasso.gaussian(X, y, lam_CV)
    #L.covariance_estimator = glm_sandwich_estimator(L.loglike, B=2000)
    #soln = L.fit()
    problem = rr.simple_problem(glm_loss, rr.l1norm(p, lagrange=cv.lam_CVR))
    beta_hat = problem.solve()
    active_hat = beta_hat !=0
    print("non-randomized lasso ", active_hat.sum())

    # view 2
    W = np.ones(p) * cv.lam_CVR
    penalty = rr.group_lasso(np.arange(p),
                             weights=dict(zip(np.arange(p), W)), lagrange=1.)
    epsilon = 1./np.sqrt(n)
    M_est1 = glm_group_lasso(glm_loss, epsilon, penalty, randomizer)

    mv = multiple_queries([cv, M_est1])
    mv.solve()

    #active = soln != 0
    active_union = M_est1._overall
    nactive = np.sum(active_union)
    print("nactive", nactive)


    nonzero = np.where(beta)[0]
    if set(nonzero).issubset(np.nonzero(active_union)[0]):

        active_set = np.nonzero(active_union)[0]
        true_vec = beta[active_union]

        if marginalize_subgrad == True:
            M_est1.decompose_subgradient(conditioning_groups=np.zeros(p, dtype=bool),
                                         marginalizing_groups=np.ones(p, bool))

        target_sampler, target_observed = glm_target(glm_loss,
                                                     active_union,
                                                     mv,
                                                     bootstrap=bootstrap)

        if intervals == 'old':
            target_sample = target_sampler.sample(ndraw=ndraw,
                                                  burnin=burnin)
            LU = target_sampler.confidence_intervals(target_observed,
                                                     sample=target_sample,
                                                     level=0.9)

            #pivots_mle = target_sampler.coefficient_pvalues(target_observed,
            #                                                parameter=target_sampler.reference,
            #                                                sample=target_sample)
            pivots_truth = target_sampler.coefficient_pvalues(target_observed,
                                                              parameter=true_vec,
                                                              sample=target_sample)
            #pvalues = target_sampler.coefficient_pvalues(target_observed,
            #                                             parameter=np.zeros_like(true_vec),
            #                                             sample=target_sample)
        else:
            full_sample = target_sampler.sample(ndraw=ndraw,
                                                burnin=burnin,
                                                keep_opt=True)
            LU = target_sampler.confidence_intervals_translate(target_observed,
                                                               sample=full_sample,
                                                               level=0.9)
            #pivots_mle = target_sampler.coefficient_pvalues_translate(target_observed,
            #                                                          parameter=target_sampler.reference,
            #                                                          sample=full_sample)
            pivots_truth = target_sampler.coefficient_pvalues_translate(target_observed,
                                                                        parameter=true_vec,
                                                                        sample=full_sample)
            #pvalues = target_sampler.coefficient_pvalues_translate(target_observed,
            #                                                       parameter=np.zeros_like(true_vec),
            #                                                       sample=full_sample)

        LU_naive = naive_confidence_intervals(target_sampler, target_observed)

        L, U = LU.T

        covered = np.zeros(nactive, np.bool)
        naive_covered = np.zeros(nactive, np.bool)
        active_var = np.zeros(nactive, np.bool)

        for j in range(nactive):
            if (L[j] <= true_vec[j]) and (U[j] >= true_vec[j]):
                covered[j] = 1
            if (LU_naive[j, 0] <= true_vec[j]) and (LU_naive[j, 1] >= true_vec[j]):
                naive_covered[j] = 1
            active_var[j] = active_set[j] in nonzero

        print("individual coverage", np.true_divide(covered.sum(),nactive))
        return pivots_truth, covered, naive_covered, active_var


def report(niter=50, **kwargs):
    kwargs = {'s': 0, 'n': 500, 'p': 50, 'snr': 7, 'bootstrap': False, 'randomizer': 'gaussian'}
    intervals_report = reports.reports['test_cv']
    CLT_runs = reports.collect_multiple_runs(intervals_report['test'],
                                             intervals_report['columns'],
                                             niter,
                                             reports.summarize_all,
                                             **kwargs)

    # fig = reports.pivot_plot(CLT_runs, color='b', label='CLT')
    fig = reports.pivot_plot_2in1(CLT_runs, color='b', label='CV')

    #kwargs['bootstrap'] = True
    #bootstrap_runs = reports.collect_multiple_runs(intervals_report['test'],
    #                                               intervals_report['columns'],
    #                                               niter,
    #                                               reports.summarize_all,
    #                                               **kwargs)

    # fig = reports.pivot_plot(bootstrap_runs, color='g', label='Bootstrap', fig=fig)
    #fig = reports.pivot_plot_2in1(bootstrap_runs, color='g', label='Bootstrap', fig=fig)

    fig.savefig('cv_pivots.pdf')  # will have both bootstrap and CLT on plot


if __name__ == '__main__':
    report()