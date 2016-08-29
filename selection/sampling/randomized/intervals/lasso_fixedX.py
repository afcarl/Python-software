import numpy as np
from scipy.optimize import minimize, bisect
from selection.sampling.randomized.tests.test_lasso_fixedX_saturated import test_lasso
import selection.sampling.randomized.api as randomized
from scipy.stats import laplace, probplot, uniform
from selection.algorithms.lasso import instance
import regreg.api as rr
from matplotlib import pyplot as plt

plt.figure()
plt.ion()


def joint_Gaussian_parameters(X, y, active, signs, j, epsilon, lam, sigma, tau):

    n, p = X.shape
    nactive = np.sum(active)
    ninactive = p-nactive

    mat = np.linalg.pinv(X[:, active])
    eta = mat[j, :]

    #from Snigdha's R code:
    #XE = X[:,active]
    #if nactive>1:
    #    keep = np.ones(nactive, dtype=bool)
    #    keep[j] = False
    #    eta = (np.identity(n)- np.dot(XE[:, keep], np.linalg.pinv(XE[:,keep]))).dot(XE[:,j])
    #else:
    #    eta = np.true_divide(XE[:,j], np.linalg.norm(XE[:,j])**2)


    c = np.true_divide(eta, np.linalg.norm(eta) ** 2)

    A = np.zeros((p, p + 1))
    A[:, 0] = -np.dot(X.T, c)
    A[:, 1:(nactive + 1)] = np.dot(X.T, X[:, active])
    A[:nactive, 1:(nactive + 1)] += epsilon * np.identity(nactive)
    A[nactive:, (nactive + 1):] = lam * np.identity(ninactive)

    fixed_part = np.dot(np.identity(n) - np.outer(c, eta), y)

    gamma = -np.dot(X.T, fixed_part)
    gamma[:nactive] += lam * signs

    v = np.zeros(p + 1)
    v[0] = 1

    Sigma_inv = np.true_divide(np.dot(A.T, A), tau ** 2) + np.true_divide(np.outer(v, v), sigma ** 2)
    Sigma_inv_mu = np.true_divide(np.dot(A.T, gamma), tau ** 2)

    return Sigma_inv, Sigma_inv_mu



def log_selection_probability(param, Sigma_full, Sigma_inv, Sigma_inv_mu, sigma,
                              nactive, ninactive, signs, betaE):
    #print 'param value', param
    p = nactive+ninactive
    Sigma_inv_mu_modified = Sigma_inv_mu.copy()
    Sigma_inv_mu_modified[0] += param/(sigma ** 2)

    initial_guess = np.zeros(p + 1)
    initial_guess[1:(nactive + 1)] = betaE
    initial_guess[(nactive+1):] = np.random.uniform(-1,1,ninactive)

    bounds = ((None, None),)
    for i in range(nactive):
        if signs[i] < 0:
            bounds += ((None, 0),)
        else:
            bounds += ((0, None),)
    bounds += ((-1, 1),) * ninactive

    def chernoff(x):
        return np.inner(x, Sigma_inv.dot(x))/2 - np.inner(Sigma_inv_mu_modified, x)

    def barrier(x):
        # Ax\leq b
        A = np.zeros((nactive+2*ninactive, 1+nactive+ninactive))
        A[:nactive, 1:(nactive+1)] = -np.diag(signs)
        A[nactive:(nactive+ninactive), (nactive+1):] = np.identity(ninactive)
        A[(nactive+ninactive):, (nactive+1):] = -np.identity(ninactive)
        b = np.zeros(nactive+2*ninactive)
        b[nactive:] = 1

        if all(b-np.dot(A,x)>=np.power(10,-9)):
            return np.sum(np.log(1+np.true_divide(1,b-np.dot(A,x))))

        return (nactive+ninactive)*(10**9)

    def objective(x):
        return chernoff(x)+barrier(x)

    res = minimize(objective, x0=initial_guess) #, bounds=bounds)
    #print nactive, ninactive
    #print signs
    #print nactive
    #print res.x
    mu = np.dot(Sigma_full, Sigma_inv_mu_modified)
    return - np.true_divide(np.inner(mu, Sigma_inv_mu_modified), 2) - res.fun
    #return -np.inner(mu, Sigma_inv_mu_modified) / 2 - objective(res.x)


def intervals(n=50, p=10, s=0, alpha=0.1):

    X, y, true_beta, nonzero, sigma = instance(n=n, p=p, random_signs=True, s=s, snr =2, sigma=1., rho=0)
    print sigma
    print true_beta
    random_Z = np.random.standard_normal(p)

    null, alt, all_observed, all_variances, all_samples, active, betaE, lam = test_lasso(X,y, nonzero, sigma, random_Z, "normal")
    if np.sum(null) < 0:
        return 0, 0

    n, p = X.shape
    print 'true beta', true_beta
    print active
    tau = 1.
    epsilon = 1. / np.sqrt(n)

    inactive = ~active
    signs = np.sign(betaE)
    nactive = np.sum(active)
    print 'size of the active set', nactive
    if nactive==0:
        print "no active covariates"
        return -1
    ninactive = np.sum(inactive)
    active_set = np.where(active)[0]

    coverage = 0

    if set(nonzero).issubset(active_set):
        for j, idx in enumerate(active_set):
            truth = true_beta[idx]

            Sigma_inv, Sigma_inv_mu = joint_Gaussian_parameters(X,y, active, signs, j, epsilon, lam, sigma, tau)
            Sigma_full = np.linalg.inv(Sigma_inv)
            log_sel_prob_ref = log_selection_probability(0, Sigma_full, Sigma_inv, Sigma_inv_mu, sigma,
                                                         nactive, ninactive, signs, betaE)

            print 'log sel prob ref', log_sel_prob_ref

            param_values = np.linspace(-5, 5, num=200)
            log_sel_prob_param = np.zeros(param_values.shape[0])
            for i in range(param_values.shape[0]):
                 log_sel_prob_param[i] = log_selection_probability(param_values[i], Sigma_full, Sigma_inv, Sigma_inv_mu, sigma,
                                                                   nactive, ninactive, signs, betaE)
            plt.clf()
            print log_sel_prob_param
            plt.plot(param_values, log_sel_prob_param)
            plt.pause(0.01)

            # obs = all_observed[j]
            # sd = np.sqrt(all_variances[j])
            # indicator = np.array(all_samples[j,:]<all_observed[j], dtype =int)
            # pop = all_samples[j,:]
            # variance = all_variances[j]
            #
            # def pvalue_by_tilting(param_value, variance=variance, pop=pop, indicator =indicator):
            #     #log_sel_prob_param = log_selection_probability(param_value, Sigma_full, Sigma_inv, Sigma_inv_mu, sigma,
            #     #                                               nactive, ninactive, signs, betaE)
            #     #print 'log sele prob',log_sel_prob_param
            #     #if log_sel_prob_param <- 100:
            #     #    return 0
            #     log_LR = pop*param_value/(2*variance)-param_value**2/(2*variance)
            #     #log_LR += log_sel_prob_ref - log_sel_prob_param
            #     #print log_LR
            #     return np.clip(np.sum(np.multiply(indicator, np.exp(log_LR)))/ indicator.shape[0], 0,1)
            #
            # #print 'pvalue at the truth', pvalue_by_tilting(0)
            # #print 'pvalue at the truth', pvalue_by_tilting(0)
            #
            # #print 'param value', param_values
            # pvalues = np.zeros(param_values.shape[0])
            #
            # for i in range(param_values.shape[0]):
            #     #print param_values[i]
            #     #print pvalue_by_tilting(param_values[i])
            #     pvalues[i] = pvalue_by_tilting(param_values[i])
            #     log_sel_prob_param[i] = log_selection_probability(param_values[i], Sigma_full, Sigma_inv, Sigma_inv_mu, sigma,
            #                                                       nactive, ninactive, signs, betaE)
            #     #print pvalues[i]
            #     #print param_values[i], pvalue_by_tilting(param_values[i])
            #
            # #pvalues = [pvalue_by_tilting(param_values[i]) for i in range(param_values.shape[0])]
            # #pvalues = np.asarray(pvalues, dtype=np.float32)
            #
            # #print pvalues
            # #print 'sum', np.sum(np.abs(pvalues-1.+alpha/2)<0.1)
            # #cl_zero= pvalue_by_tilting(param_values[np.argmin(np.abs(param_values))])
            # #print 'closest to zero pvalue exists' , cl_zero
            #
            # accepted_indices = np.multiply(np.array(pvalues>alpha/2), np.array(pvalues<1.-alpha/2))
            # #print accepted_indices
            # if np.sum(accepted_indices)==0:
            #     L=0
            #     U=0
            # else:
            #     L = np.min(param_values[accepted_indices])
            #     U = np.max(param_values[accepted_indices])
            #
            # #L = param_values[np.argmin(np.abs(pvalues-(alpha/2)))]
            # #U = param_values[np.argmin(np.abs(pvalues-1.+(alpha/2)))]
            # #print 'truth', np.abs(pvalue_by_tilting(0)-1.+(alpha/2)), np.abs(pvalue_by_tilting(0)-(alpha/2))
            # #print "min", np.min(np.abs(pvalues-1.+(alpha/2)))
            # #print "min", np.min(np.abs(pvalues-(alpha/2)))
            # #print "pvalue at L", pvalue_by_tilting(L)
            # #print "pvalue at U", pvalue_by_tilting(U)
            # #print 'truth', truth
            # print "interval",  L, U
            # #print 'pvalue at the truth', pvalue_by_tilting(0)
            #
            # if (L<=truth) and (U>=truth):
            #     coverage +=1
            # if (U <= truth) and (L >= truth):
            #     coverage += 1
            #
            # #plt.clf()
            # #plt.plot(param_values, pvalues, 'o')
            # #plt.pause(0.01)

    return 0,0
    #return coverage, nactive


total_coverage = 0
total_number = 0


for i in range(50):
    print "iteration", i
    coverage, nactive = intervals()
    total_coverage += coverage
    total_number += nactive

print "total coverage", np.true_divide(total_coverage, total_number)


while True:
    plt.pause(0.05)
plt.show()










