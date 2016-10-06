import numpy as np
from scipy.stats import norm as ndist

import regreg.api as rr

from selection.randomized.api import (randomization, 
                                      multiple_views, 
                                      pairs_bootstrap_glm, 
                                      glm_nonparametric_bootstrap,
                                      glm_threshold_score)

from selection.randomized.glm import bootstrap_cov
from selection.distributions.discrete_family import discrete_family
from selection.sampling.langevin import projected_langevin
from selection.tests.decorators import wait_for_return_value, set_seed_for_test, set_sampling_params_iftrue

from selection.tests.instance import logistic_instance


@set_sampling_params_iftrue(True, ndraw=100, burnin=100)
@set_seed_for_test()
@wait_for_return_value()
def test_threshold_score(ndraw=10000, burnin=2000, nsim=None): # nsim needed for decorator

    s, n, p = 5, 200, 20 
    threshold = 0.5

    X, y, beta, _ = logistic_instance(n=n, p=p, s=s, rho=0.1, snr=7)

    nonzero = np.where(beta)[0]
    lam_frac = 1.

    loss = rr.glm.logistic(X, y)
    active_bool = np.zeros(p, np.bool)
    active_bool[range(3)] = 1
    inactive_bool = ~active_bool
    randomizer = randomization.laplace((inactive_bool.sum(),), scale=0.5)

    # threshold the score

    thresh = glm_threshold_score(loss, 
                                 threshold,
                                 randomizer,
                                 active_bool,
                                 inactive_bool)
    mv = multiple_views([thresh])
    mv.solve()

    boundary = thresh.boundary
    new_active = np.nonzero(np.arange(3,20)[boundary])[0]
    active_set = np.array(sorted(set(range(3)).union(new_active)))

    if set(nonzero).issubset(active_set):

        full_active = np.zeros(p, np.bool)
        full_active[active_set] = 1
        nactive = active_set.shape[0]
        inactive_selected = I = [i for i in np.arange(active_set.shape[0]) if active_set[i] not in nonzero]


        inactive_indicators_mat = np.zeros((len(inactive_selected),nactive))
        j = 0
        for i in range(nactive):
            if active_set[i] not in nonzero:
                inactive_indicators_mat[j,i] = 1
                j+=1

        form_covariances = glm_nonparametric_bootstrap(n, n)
        mv.setup_sampler(form_covariances)

        boot_target, target_observed = pairs_bootstrap_glm(loss, full_active)
        inactive_target = lambda indices: boot_target(indices)[inactive_selected]
        inactive_observed = target_observed[inactive_selected]
        # param_cov = _parametric_cov_glm(loss, active_union)

        target_sampler = mv.setup_target(inactive_target, inactive_observed)

        test_stat = lambda x: np.linalg.norm(x)
        pval = target_sampler.hypothesis_test(test_stat,
                                              np.linalg.norm(inactive_observed), 
                                              alternative='twosided',
                                              ndraw=ndraw,
                                              burnin=burnin)
        return pval
