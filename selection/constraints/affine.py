"""
This module contains the core code needed for post selection
inference based on affine selection procedures as
described in the papers `Kac Rice`_, `Spacings`_, `covTest`_
and `post selection LASSO`_.

.. _covTest: http://arxiv.org/abs/1301.7161
.. _Kac Rice: http://arxiv.org/abs/1308.3020
.. _Spacings: http://arxiv.org/abs/1401.3889
.. _post selection LASSO: http://arxiv.org/abs/1311.6238
.. _sample carving: http://arxiv.org/abs/1410.2597

"""

from warnings import warn
from copy import copy

import numpy as np

from ..distributions.pvalue import truncnorm_cdf, norm_interval
from ..truncated.gaussian import truncated_gaussian, truncated_gaussian_old
from ..sampling.truncnorm import (sample_truncnorm_white, 
                                  sample_truncnorm_white_sphere)

from ..distributions.discrete_family import discrete_family
from mpmath import mp
import pyinter

WARNINGS = False

class constraints(object):

    r"""
    This class is the core object for affine selection procedures.
    It is meant to describe sets of the form $C$
    where

    .. math::

       C = \left\{z: Az\leq b \right \}

    Its main purpose is to consider slices through $C$
    and the conditional distribution of a Gaussian $N(\mu,\Sigma)$
    restricted to such slices.

    Notes
    -----

    In this parameterization, the parameter `self.mean` corresponds
    to the *reference measure* that is being truncated. It is not the
    mean of the truncated Gaussian.

    >>> import numpy as np, selection.affine as affine
    >>> positive = affine.constraints(-np.identity(2), np.zeros(2))
    >>> Y = np.array([3,4.4])
    >>> eta = np.array([1,1])
    >>> positive.interval(eta, Y)
    array([  4.6212814 ,  10.17180724])
    >>> positive.pivot(eta, Y)
    No
    >>> positive.bounds(eta, Y)
    (1.3999999999999988, 7.4000000000000004, inf, 1.4142135623730951)
    >>> 

    """

    def __init__(self, 
                 linear_part,
                 offset,
                 covariance=None,
                 mean=None):
        r"""
        Create a new inequality. 

        Parameters
        ----------

        linear_part : np.float((q,p))
            The linear part, $A$ of the affine constraint
            $\{z:Az \leq b\}$. 

        offset: np.float(b)
            The offset part, $b$ of the affine constraint
            $\{z:Az \leq b\}$. 

        covariance : np.float
            Covariance matrix of Gaussian distribution to be 
            truncated. Defaults to `np.identity(self.dim)`.

        mean : np.float
            Mean vector of Gaussian distribution to be 
            truncated. Defaults to `np.zeros(self.dim)`.

        """

        self.linear_part, self.offset = \
            np.asarray(linear_part), np.asarray(offset)
        
        if self.linear_part.ndim == 2:
            self.dim = self.linear_part.shape[1]
        else:
            self.dim = self.linear_part.shape[0]

        if covariance is None:
            covariance = np.identity(self.dim)
        self.covariance = covariance

        if mean is None:
            mean = np.zeros(self.dim)
        self.mean = mean

    def _repr_latex_(self):
        """
        >>> A = np.array([[ 0.32,  0.27,  0.19],
       [ 0.59,  0.98,  0.71],
       [ 0.34,  0.15,  0.17 ,  0.25], 
        >>> B = np.array([ 0.51,  0.74,  0.72 ,  0.82])
        >>> C = constraints(A, B)
        >>> C._repr_latex
        "$$Z \sim N(\mu,\Sigma) | AZ \leq b$$"
        """
        return """$$Z \sim N(\mu,\Sigma) | AZ \leq b$$"""

    def __copy__(self):
        r"""
        A copy of the constraints.

        Also copies _sqrt_cov, _sqrt_inv if attributes are present.
        """
        con = constraints(self.linear_part.copy(),
                          self.offset.copy(),
                          mean=copy(self.mean),
                          covariance=copy(self.covariance))
        if hasattr(self, "_sqrt_cov"):
            con._sqrt_cov = self._sqrt_cov.copy()
            con._sqrt_inv = self._sqrt_inv.copy()
                          
        return con

    def __call__(self, Y, tol=1.e-3):
        r"""
        Check whether Y satisfies the linear
        inequality constraints.
        >>> A = np.array([[1., -1.], [1., -1.]])
        >>> B = np.array([1., 1.])
        >>> con = constraints(A, B)
        >>> Y = np.array([-1., 1.])
        >>> con(Y)
        True
        """
        V1 = np.dot(self.linear_part, Y) - self.offset
        return np.all(V1 < tol * np.fabs(V1).max())

    def conditional(self, linear_part, value):
        """
        Return an equivalent constraint 
        after having conditioned on a linear equality.
        
        Let the inequality constraints be specified by
        `(A,b)` and the equality constraints be specified
        by `(C,d)`. We form equivalent inequality constraints by 
        considering the residual

        .. math::
           
           AY - E(AY|CZ=d)

        """

        A, b, S = self.linear_part, self.offset, self.covariance
        C, d = linear_part, value

        M1 = np.dot(S, C.T)
        M2 = np.dot(C, M1)
        if M2.shape:
            M2i = np.linalg.pinv(M2)
            delta_cov = np.dot(M1, np.dot(M2i, M1.T))
            delta_offset = 0 * np.dot(M1, np.dot(M2i, d))
            delta_mean = \
            np.dot(M1,
                   np.dot(M2i,
                          np.dot(C,
                                 self.mean) - d))
        else:
            M2i = 1. / M2
            delta_cov = np.multiply.outer(M1, M1) / M2i
            delta_mean = M1 * d  / M2i

        return constraints(self.linear_part,
                           self.offset - np.dot(self.linear_part, delta_offset),
                           covariance=self.covariance - delta_cov,
                           mean=self.mean - delta_mean)

    def bounds(self, direction_of_interest, Y):
        r"""
        For a realization $Y$ of the random variable $N(\mu,\Sigma)$
        truncated to $C$ specified by `self.constraints` compute
        the slice of the inequality constraints in a 
        given direction $\eta$.

        Parameters
        ----------

        direction_of_interest: np.float
            A direction $\eta$ for which we may want to form 
            selection intervals or a test.

        Y : np.float
            A realization of $N(\mu,\Sigma)$ where 
            $\Sigma$ is `self.covariance`.

        Returns
        -------

        L : np.float
            Lower truncation bound.

        Z : np.float
            The observed $\eta^TY$

        U : np.float
            Upper truncation bound.

        S : np.float
            Standard deviation of $\eta^TY$.

        
        """
        return interval_constraints(self.linear_part,
                                    self.offset,
                                    self.covariance,
                                    Y,
                                    direction_of_interest)

    def pivot(self, direction_of_interest, Y,
              alternative='greater'):
        r"""
        For a realization $Y$ of the random variable $N(\mu,\Sigma)$
        truncated to $C$ specified by `self.constraints` compute
        the slice of the inequality constraints in a 
        given direction $\eta$ and test whether 
        $\eta^T\mu$ is greater then 0, less than 0 or equal to 0.

        Parameters
        ----------

        direction_of_interest: np.float
            A direction $\eta$ for which we may want to form 
            selection intervals or a test.

        Y : np.float
            A realization of $N(0,\Sigma)$ where 
            $\Sigma$ is `self.covariance`.

        alternative : ['greater', 'less', 'twosided']
            What alternative to use.

        Returns
        -------

        P : np.float
            $p$-value of corresponding test.

        Notes
        -----

        All of the tests are based on the exact pivot $F$ given
        by the truncated Gaussian distribution for the
        given direction $\eta$. If the alternative is 'greater'
        then we return $1-F$; if it is 'less' we return $F$
        and if it is 'twosided' we return $2 \min(F,1-F)$.

        
        """
        if alternative not in ['greater', 'less', 'twosided']:
            raise ValueError("alternative should be one of ['greater', 'less', 'twosided']")
        L, Z, U, S = self.bounds(direction_of_interest, Y)
        meanZ = (direction_of_interest * self.mean).sum()
        P = truncnorm_cdf((Z-meanZ)/S, (L-meanZ)/S, (U-meanZ)/S)
        if alternative == 'greater':
            return 1 - P
        elif alternative == 'less':
            return P
        else:
            return 2 * min(P, 1-P)

    def interval(self, direction_of_interest, Y,
                 alpha=0.05, UMAU=False):
        r"""
        For a realization $Y$ of the random variable $N(\mu,\Sigma)$
        truncated to $C$ specified by `self.constraints` compute
        the slice of the inequality constraints in a 
        given direction $\eta$ and test whether 
        $\eta^T\mu$ is greater then 0, less than 0 or equal to 0.
        
        Parameters
        ----------

        direction_of_interest: np.float

            A direction $\eta$ for which we may want to form 
            selection intervals or a test.

        Y : np.float

            A realization of $N(0,\Sigma)$ where 
            $\Sigma$ is `self.covariance`.

        alpha : float

            What level of confidence?

        UMAU : bool

            Use the UMAU intervals?

        Returns
        -------

        [U,L] : selection interval

        
        """
        ## THE DOCUMENTATION IS NOT GOOD ! HAS TO BE CHANGED !

        return selection_interval( \
            self.linear_part,
            self.offset,
            self.covariance,
            Y,
            direction_of_interest,
            alpha=alpha,
            UMAU=UMAU)

    def whiten(self):
        """
        Parameters
        ----------

        Return a whitened version of constraints in a different
        basis, and a change of basis matrix.

        If `self.covariance` is rank deficient, the change-of
        basis matrix will not be square.

        """

        if not hasattr(self, "_sqrt_cov"):
            rank = np.linalg.matrix_rank(self.covariance)

            D, U = np.linalg.eigh(self.covariance)
            D = np.sqrt(D[-rank:])
            U = U[:,-rank:]
        
            self._sqrt_cov = U * D[None,:]
            self._sqrt_inv = (U / D[None,:]).T

        sqrt_cov = self._sqrt_cov
        sqrt_inv = self._sqrt_inv

        # original matrix is np.dot(U, U.T)

        new_A = np.dot(self.linear_part, sqrt_cov)
        den = np.sqrt((new_A**2).sum(1))
        new_b = self.offset - np.dot(self.linear_part, self.mean)
        new_con = constraints(new_A / den[:,None], new_b / den)

        mu = self.mean.copy()
        inverse_map = lambda Z: np.dot(sqrt_cov, Z) + mu[:,None]
        forward_map = lambda W: np.dot(sqrt_inv, W - mu)

        return inverse_map, forward_map, new_con

def stack(*cons):
    """
    Combine constraints into a large constaint
    by intersection. 

    Parameters
    ----------

    cons : [`selection.affine.constraints`_]
         A sequence of constraints.

    Returns
    -------

    intersection : `selection.affine.constraints`_

    Notes
    -----

    Resulting constraint will have mean 0 and covariance $I$.

    """
    ineq, ineq_off = [], []
    eq, eq_off = [], []
    for con in cons:
        ineq.append(con.linear_part)
        ineq_off.append(con.offset)

    intersection = constraints(np.vstack(ineq), 
                               np.hstack(ineq_off))
    return intersection

def interval_constraints(support_directions, 
                         support_offsets,
                         covariance,
                         observed_data, 
                         direction_of_interest,
                         tol = 1.e-4):
    r"""
    Given an affine in cone constraint $\{z:Az+b \leq 0\}$ (elementwise)
    specified with $A$ as `support_directions` and $b$ as
    `support_offset`, a new direction of interest $\eta$, and
    an `observed_data` is Gaussian vector $Z \sim N(\mu,\Sigma)$ 
    with `covariance` matrix $\Sigma$, this
    function returns $\eta^TZ$ as well as an interval
    bounding this value. 

    The interval constructed is such that the endpoints are 
    independent of $\eta^TZ$, hence the $p$-value
    of `Kac Rice`_
    can be used to form an exact pivot.

    Parameters
    ----------

    support_directions : np.float
         Matrix specifying constraint, $A$.

    support_offset : np.float
         Offset in constraint, $b$.

    covariance : np.float
         Covariance matrix of `observed_data`.

    observed_data : np.float
         Observations.

    direction_of_interest : np.float
         Direction in which we're interested for the
         contrast.

    tol : float
         Relative tolerance parameter for deciding 
         sign of $Az-b$.

    Returns
    -------

    lower_bound : float

    observed : float

    upper_bound : float

    sigma : float

    """

    # shorthand
    A, b, S, X, w = (support_directions,
                     support_offsets,
                     covariance,
                     observed_data,
                     direction_of_interest)

    U = np.dot(A, X) - b
    if not np.all(U  < tol * np.fabs(U).max()) and WARNINGS:
        warn('constraints not satisfied: %s' % `U`)

    Sw = np.dot(S, w)
    sigma = np.sqrt((w*Sw).sum())
    alpha = np.dot(A, Sw) / sigma**2
    V = (w*X).sum() # \eta^TZ

    # adding the zero_coords in the denominator ensures that
    # there are no divide-by-zero errors in RHS
    # these coords are never used in upper_bound or lower_bound

    zero_coords = alpha == 0
    RHS = (-U + V * alpha) / (alpha + zero_coords)
    RHS[zero_coords] = np.nan

    pos_coords = alpha > tol * np.fabs(alpha).max()
    if np.any(pos_coords):
        upper_bound = RHS[pos_coords].min()
    else:
        upper_bound = np.inf
    neg_coords = alpha < -tol * np.fabs(alpha).max()
    if np.any(neg_coords):
        lower_bound = RHS[neg_coords].max()
    else:
        lower_bound = -np.inf

    return lower_bound, V, upper_bound, sigma

def selection_interval(support_directions, 
                       support_offsets,
                       covariance,
                       observed_data, 
                       direction_of_interest,
                       tol = 1.e-4,
                       alpha = 0.05,
                       UMAU=True):
    """
    Given an affine in cone constraint $\{z:Az+b \leq 0\}$ (elementwise)
    specified with $A$ as `support_directions` and $b$ as
    `support_offset`, a new direction of interest $\eta$, and
    an `observed_data` is Gaussian vector $Z \sim N(\mu,\Sigma)$ 
    with `covariance` matrix $\Sigma$, this
    function returns a confidence interval
    for $\eta^T\mu$.

    Parameters
    ----------

    support_directions : np.float
         Matrix specifying constraint, $A$.

    support_offset : np.float
         Offset in constraint, $b$.

    covariance : np.float
         Covariance matrix of `observed_data`.

    observed_data : np.float
         Observations.

    direction_of_interest : np.float
         Direction in which we're interested for the
         contrast.

    tol : float
         Relative tolerance parameter for deciding 
         sign of $Az-b$.

    UMAU : bool
         Use the UMAU interval, or twosided pivot.

    Returns
    -------

    selection_interval : (float, float)

    """

    lower_bound, V, upper_bound, sigma = interval_constraints( \
        support_directions, 
        support_offsets,
        covariance,
        observed_data, 
        direction_of_interest,
        tol=tol)

    truncated = truncated_gaussian_old([(lower_bound, upper_bound)], sigma=sigma)
    if UMAU:
        _selection_interval = truncated.UMAU_interval(V, alpha)
    else:
        _selection_interval = truncated.equal_tailed_interval(V, alpha)
    
    return _selection_interval

def one_parameter_MLE(constraint, 
                      Y,
                      direction_of_interest,
                      how_often=-1,
                      ndraw=500,
                      burnin=500,
                      niter=20, 
                      white=False,
                      step_size=0.9,
                      hessian_min=1.,
                      tol=1.e-5,
                      startMLE=None):
    r"""
    Find one parameter MLE for family

    .. math::

        \frac{dP_{\theta}}{dP_0}(y) \propto \exp(\theta \cdot \eta^Ty)

    where $\eta$ is `direction_of_interest` and $P_0$ is the truncated
    Gaussian distribution defined by `constraint`.

    Parameters
    ----------

    constraint : `selection.affine.constraints`_

    Y : np.float
        Point satisfying the constraint.

    direction_of_interest : np.float
        Natural parameter whose span determines the one-parameter
        family.

    how_often : int (optional)
        How often should the sampler make a move along `direction_of_interest`?
        If negative, defaults to ndraw+burnin (so it will never be used).

    ndraw : int (optional)
        Defaults to 500.

    burnin : int (optional)
        Defaults to 500.

    niter : int (optional)
        How many Newton steps should we take? Defaults to 10. 

    white : bool (optional)
        Is con.covariance equal to identity?

    step_size : float
        What proportion of Newton step should we take?

    min_hessian : float (optional)    
        Lower bound on Hessian (will help taking too large a step).

    tol : float (optional)    
        Tolerance for convergance. Iteration stops
        when sqrt(grad**2 / hessian) < tol

    startMLE : float (optional)
        Initial condition for iteration. If None,
        default starting point is unconstrained MLE.
    Returns
    -------

    MLE : float
        Maximum pseudolikelihood estimate.
        
    """

    con, eta = constraint, direction_of_interest # shorthand
    observed = (eta*Y).sum()

    if how_often < 0:
        how_often = ndraw + burnin

    # we take the unconstrained MLE as starting point
    # to see this, note that we are changing the mean by \theta * \Sigma \eta
    # which means the negative log-likelihood is 
    # \frac{\theta^2}{2} (\eta^T\Sigma\eta) - \theta \eta^Ty

    unconstrained_MLE = observed / np.dot(eta, np.dot(con.covariance, eta))
    if startMLE is None:
        MLE = unconstrained_MLE
    else:
        MLE = startMLE
    
    samples = []

    con_cp = copy(con)
    for iter_count in range(niter):
        tilt = MLE * eta
        con_cp.mean[:] = con.mean + np.dot(con.covariance, tilt)

        if not white:
            inverse_map, forward_map, white_con = con_cp.whiten()
            white_Y = forward_map(Y)
            white_direction_of_interest = forward_map(np.dot(con_cp.covariance, eta))
        else:
            white_con = con_cp
            inverse_map = lambda V: V

        cur_sample = sample_truncnorm_white(white_con.linear_part,
                                            white_con.offset,
                                            white_Y, 
                                            white_direction_of_interest,
                                            how_often=how_often,
                                            ndraw=ndraw, 
                                            burnin=burnin,
                                            sigma=1.,
                                            use_A=False)

        Z = inverse_map(cur_sample.T).T

        Zeta = np.dot(Z, eta)
        samples.append((MLE, Zeta))

        sum_mean = 0.
        sum_second_moment = 0.
        sum_weights = 0.

        weight_adjust = -np.inf
        lag = len(samples)

        for sample in samples[-lag:]:

            # each previous sample is from a different value of
            # the natural parameter, i.e. exp(param * np.dot(eta, y))
            # but to evaluate the current meal, we want
            # exp(MLE * np.dot(eta, y))

            prev_param, prev_sufficient_stat = sample
            weight_adjust = max(weight_adjust, ((MLE - prev_param) * prev_sufficient_stat).max())
            
        weight_adjust -= 4.

        for sample in samples[-lag:]:

            prev_param, prev_sufficient_stat = sample
            weight_correction = np.exp((MLE - prev_param) * prev_sufficient_stat - weight_adjust)

            sum_mean += weight_correction * prev_sufficient_stat
            sum_second_moment += weight_correction * prev_sufficient_stat**2
            sum_weights += weight_correction

        weighted_mean = sum_mean.sum() / sum_weights.sum()
        weighted_second_moment = sum_second_moment.sum() / sum_weights.sum()

        grad = (weighted_mean - observed)
        hessian = weighted_second_moment - weighted_mean**2

        step = - step_size * grad / (max(hessian, hessian_min))
        MLE += step

        if np.sqrt(grad**2 / (max(hessian, hessian_min))) < tol:
            break

    DEBUG = False
    if DEBUG:
        # observed should match weighted_mean
        print observed, weighted_mean, MLE

    return MLE

def sample_from_constraints(con, 
                            Y,
                            direction_of_interest=None,
                            how_often=-1,
                            ndraw=1000,
                            burnin=1000,
                            white=False,
                            use_constraint_directions=True):
    r"""
    Use Gibbs sampler to simulate from `con`.

    Parameters
    ----------

    con : `selection.affine.constraints`_

    Y : np.float
        Point satisfying the constraint.

    direction_of_interest : np.float (optional)
        Which projection is of most interest?

    how_often : int (optional)
        How often should the sampler make a move along `direction_of_interest`?
        If negative, defaults to ndraw+burnin (so it will never be used).

    ndraw : int (optional)
        Defaults to 1000.

    burnin : int (optional)
        Defaults to 1000.

    white : bool (optional)
        Is con.covariance equal to identity?

    use_constraint_directions : bool (optional)
        Use the directions formed by the constraints as in
        the Gibbs scheme?

    Returns
    -------

    Z : np.float((ndraw, n))
        Sample from the sphere intersect the constraints.
        
    """

    if direction_of_interest is None:
        direction_of_interest = np.random.standard_normal(Y.shape)
    if how_often < 0:
        how_often = ndraw + burnin

    if not white:
        inverse_map, forward_map, white_con = con.whiten()
        white_Y = forward_map(Y)
        white_direction_of_interest = forward_map(np.dot(con.covariance, direction_of_interest))
    else:
        white_con = con
        inverse_map = lambda V: V

    white_samples = sample_truncnorm_white(white_con.linear_part,
                                           white_con.offset,
                                           white_Y, 
                                           white_direction_of_interest,
                                           how_often=how_often,
                                           ndraw=ndraw, 
                                           burnin=burnin,
                                           sigma=1.,
                                           use_A=use_constraint_directions)
    Z = inverse_map(white_samples.T).T
    return Z

def sample_from_sphere(con, 
                       Y,
                       direction_of_interest=None,
                       how_often=-1,
                       ndraw=1000,
                       burnin=1000,
                       white=False):
    r"""
    Use Gibbs sampler to simulate from `con` 
    intersected with (whitened) sphere of radius `np.linalg.norm(Y)`.
    When `con.covariance` is not $I$, it samples from the
    ellipse of constant Mahalanobis distance from `con.mean`.

    Parameters
    ----------

    con : `selection.affine.constraints`_

    Y : np.float
        Point satisfying the constraint.

    direction_of_interest : np.float (optional)
        Which projection is of most interest?

    how_often : int (optional)
        How often should the sampler make a move along `direction_of_interest`?
        If negative, defaults to ndraw+burnin (so it will never be used).

    ndraw : int (optional)
        Defaults to 1000.

    burnin : int (optional)
        Defaults to 1000.

    white : bool (optional)
        Is con.covariance equal to identity?

    Returns
    -------

    Z : np.float((ndraw, n))
        Sample from the sphere intersect the constraints.
        
    weights : np.float(ndraw)
        Importance weights for the sample.

    """
    if direction_of_interest is None:
        direction_of_interest = np.random.standard_normal(Y.shape)
    if how_often < 0:
        how_often = ndraw + burnin

    if not white:
        inverse_map, forward_map, white = con.whiten()
        white_Y = forward_map(Y)
        white_direction_of_interest = forward_map(direction_of_interest)
    else:
        white = con
        inverse_map = lambda V: V

    white_samples, weights = sample_truncnorm_white_sphere(white.linear_part,
                                                           white.offset,
                                                           white_Y, 
                                                           white_direction_of_interest,
                                                           how_often=how_often,
                                                           ndraw=ndraw, 
                                                           burnin=burnin)

    Z = inverse_map(white_samples.T).T
    return Z, weights

def gibbs_test(affine_con, Y, direction_of_interest,
               how_often=-1,
               ndraw=5000,
               burnin=2000,
               white=False,
               alternative='twosided',
               UMPU=True,
               sigma_known=False,
               alpha=0.05,
               use_constraint_directions=False):
    """
    A Monte Carlo significance test for
    a given function of `con.mean`.

    Parameters
    ----------

    affine_con : `selection.affine.constraints`_

    Y : np.float
        Point satisfying the constraint.

    direction_of_interest: np.float
        Which linear function of `con.mean` is of interest?
        (a.k.a. $\eta$ in many of related papers)

    how_often : int (optional)
        How often should the sampler make a move along `direction_of_interest`?
        If negative, defaults to ndraw+burnin (so it will never be used).

    ndraw : int (optional)
        Defaults to 1000.

    burnin : int (optional)
        Defaults to 1000.

    white : bool (optional)
        Is con.covariance equal to identity?

    alternative : str
        One of ['greater', 'less', 'twosided']

    UMPU : bool
        Perform the UMPU test?

    sigma_known : bool
        Is $\sigma$ assumed known?

    alpha : 
        Level for UMPU test.

    use_constraint_directions : bool (optional)
        Use the directions formed by the constraints as in
        the Gibbs scheme?

    Returns
    -------

    pvalue : float
        P-value (using importance weights) for specified hypothesis test.

    Z : np.float((ndraw, n))
        Sample from the sphere intersect the constraints.
        
    weights : np.float(ndraw)
        Importance weights for the sample.
    """

    eta = direction_of_interest # shorthand

    if alternative not in ['greater', 'less', 'twosided']:
        raise ValueError("expecting alternative to be in ['greater', 'less', 'twosided']")

    if not sigma_known:
        Z, W = sample_from_sphere(affine_con,
                                  Y,
                                  eta,
                                  how_often=how_often,
                                  ndraw=ndraw,
                                  burnin=burnin,
                                  white=white)
    else:
        Z = sample_from_constraints(affine_con,
                                    Y,
                                    eta,
                                    how_often=how_often,
                                    ndraw=ndraw,
                                    burnin=burnin,
                                    white=white,
                                    use_constraint_directions=\
                                        use_constraint_directions)
        W = np.ones(Z.shape[0], np.float)

    null_statistics = np.dot(Z, eta)
    observed = (eta*Y).sum()
    if alternative == 'greater':
        pvalue = (W*(null_statistics >= observed)).sum() / W.sum()
    elif alternative == 'less':
        pvalue = (W*(null_statistics <= observed)).sum() / W.sum()
    elif not UMPU:
        pvalue = (W*(null_statistics <= observed)).sum() / W.sum()
        pvalue = 2 * min(pvalue, 1 - pvalue)
    else:
        dfam = discrete_family(null_statistics, W)
        decision = dfam.two_sided_test(0, observed, alpha=alpha)
        return decision, Z, W
    return pvalue, Z, W

