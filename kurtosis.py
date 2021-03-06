

"""Tools to easily make multi voxel models"""
import numpy as np
from numpy.lib.stride_tricks import as_strided
from tqdm import tqdm

from dipy.reconst.ivim import BOUNDS, f_D_star_error, IvimFit
from dipy.core.ndindex import ndindex
from dipy.reconst.quick_squash import quick_squash as _squash
from dipy.reconst.base import ReconstFit

""" Classes and functions for fitting ivim model """
import numpy as np
from scipy.optimize import least_squares
import warnings
from dipy.reconst.base import ReconstModel
from dipy.reconst.multi_voxel import MultiVoxelFit


def multi_voxel_fitDKI(single_voxel_fit):
    """Method decorator to turn a single voxel model fit
    definition into a multi voxel model fit definition
    """
    def new_fit(self, data, dki_map, mask=None):
        """Fit method for every voxel in data"""
        # If only one voxel just return a normal fit
        if data.ndim == 1:
            return single_voxel_fit(self, data, dki_map)

        # Make a mask if mask is None
        if mask is None:
            shape = data.shape[:-1]
            strides = (0,) * len(shape)
            mask = as_strided(np.array(True), shape=shape, strides=strides)
        # Check the shape of the mask if mask is not None
        elif mask.shape != data.shape[:-1]:
            raise ValueError("mask and data shape do not match")

        # Fit data where mask is True
        fit_array = np.empty(data.shape[:-1], dtype=object)
        bar = tqdm(total=np.sum(mask), position=0)
        for ijk in ndindex(data.shape[:-1]):
            if mask[ijk]:
                fit_array[ijk] = single_voxel_fit(self, data[ijk], dki_map[ijk])
                bar.update()
        bar.close()
        return MultiVoxelFit(self, fit_array, mask)
    return new_fit


def _ivim_error(params, gtab, signal, K):
    """Error function to be used in fitting the IVIM model.
    Parameters
    ----------
    params : array
        An array of IVIM parameters - [S0, f, D_star, D]
    gtab : GradientTable class instance
        Gradient directions and bvalues.
    signal : array
        Array containing the actual signal values.
    Returns
    -------
    residual : array
        An array containing the difference between actual and estimated signal.
    """
    residual = signal - ivim_prediction(params, K, gtab)
    
    return residual


def ivim_prediction(params, K,  gtab):
    """The Intravoxel incoherent motion (IVIM) model function.
    Parameters
    ----------
    params : array
        An array of IVIM parameters - [S0, f, D_star, D].
    gtab : GradientTable class instance
        Gradient directions and bvalues.
    S0 : float, optional
        This has been added just for consistency with the existing
        API. Unlike other models, IVIM predicts S0 and this is over written
        by the S0 value in params.
    Returns
    -------
    S : array
        An array containing the IVIM signal estimated using given parameters.
    """
    b = gtab.bvals
    S0, f, D_star, D = params

    S = S0 * (f * np.exp(-b * D_star) + (1 - f) * np.exp(-b * D + (b*D**2)*K/6))

    return S

def ivim_model_selector(gtab, fit_method='DKI', **kwargs):
    """
    Selector function to switch between the 2-stage Trust-Region Reflective
    based NLLS fitting method (also containing the linear fit): `trr` and the
    Variable Projections based fitting method: `varpro`.
    Parameters
    ----------
    fit_method : string, optional
        The value fit_method can either be 'trr' or 'varpro'.
        default : trr
    """
    bounds_warning = 'Bounds for this fit have been set from experiments '
    bounds_warning += 'and literature survey. To change the bounds, please '
    bounds_warning += 'input your bounds in model definition...'

    
    ivimmodel_dki = IvimModelDKI(gtab, **kwargs)
    if 'bounds' not in kwargs:
        warnings.warn(bounds_warning, UserWarning)
    return ivimmodel_dki

IvimModel = ivim_model_selector

class IvimModelDKI(ReconstModel):
    """Ivim model
    """
    def __init__(self, gtab, split_b_D=400.0, split_b_S0=200., bounds=None,
                 two_stage=True, tol=1e-15,
                 x_scale=[1000., 0.1, 0.001, 0.0001],
                 gtol=1e-15, ftol=1e-15, eps=1e-15, maxiter=1000):
    
        r"""
        Initialize an IVIM model.
        The IVIM model assumes that biological tissue includes a volume
        fraction 'f' of water flowing with a pseudo-diffusion coefficient
        D* and a fraction (1-f) of static (diffusion only), intra and
        extracellular water, with a diffusion coefficient D. In this model
        the echo attenuation of a signal in a single voxel can be written as
            .. math::
            S(b) = S_0[f*e^{(-b*D\*)} + (1-f)e^{(-b*D)}]
            Where:
            .. math::
            S_0, f, D\* and D are the IVIM parameters.
        Parameters
        ----------
        gtab : GradientTable class instance
            Gradient directions and bvalues
        split_b_D : float, optional
            The b-value to split the data on for two-stage fit. This will be
            used while estimating the value of D. The assumption is that at
            higher b values the effects of perfusion is less and hence the
            signal can be approximated as a mono-exponential decay.
            default : 400.
        split_b_S0 : float, optional
            The b-value to split the data on for two-stage fit for estimation
            of S0 and initial guess for D_star. The assumption here is that
            at low bvalues the effects of perfusion are more.
            default : 200.
        bounds : tuple of arrays with 4 elements, optional
            Bounds to constrain the fitted model parameters. This is only
            supported for Scipy version > 0.17. When using a older Scipy
            version, this function will raise an error if bounds are different
            from None. This parameter is also used to fill nan values for out
            of bounds parameters in the `IvimFit` class using the method
            fill_na. default : ([0., 0., 0., 0.], [np.inf, .3, 1., 1.])
        two_stage : bool
            Argument to specify whether to perform a non-linear fitting of all
            parameters after the linear fitting by splitting the data based on
            bvalues. This gives more accurate parameters but takes more time.
            The linear fit can be used to get a quick estimation of the
            parameters. default : False
        tol : float, optional
            Tolerance for convergence of minimization.
            default : 1e-15
        x_scale : array, optional
            Scaling for the parameters. This is passed to `least_squares` which
            is only available for Scipy version > 0.17.
            default: [1000, 0.01, 0.001, 0.0001]
        gtol : float, optional
            Tolerance for termination by the norm of the gradient.
            default : 1e-15
        ftol : float, optional
            Tolerance for termination by the change of the cost function.
            default : 1e-15
        eps : float, optional
            Step size used for numerical approximation of the jacobian.
            default : 1e-15
        maxiter : int, optional
            Maximum number of iterations to perform.
            default : 1000
        References
        ----------
        .. [1] Le Bihan, Denis, et al. "Separation of diffusion and perfusion
               in intravoxel incoherent motion MR imaging." Radiology 168.2
               (1988): 497-505.
        .. [2] Federau, Christian, et al. "Quantitative measurement of brain
               perfusion with intravoxel incoherent motion MR imaging."
               Radiology 265.3 (2012): 874-881.
        """
        if not np.any(gtab.b0s_mask):
            e_s = "No measured signal at bvalue == 0."
            e_s += "The IVIM model requires signal measured at 0 bvalue"
            raise ValueError(e_s)

        if gtab.b0_threshold > 0:
            b0_s = "The IVIM model requires a measurement at b==0. As of "
            b0_s += "version 0.15, the default b0_threshold for the "
            b0_s += "GradientTable object is set to 50, so if you used the "
            b0_s += "default settings to initialize the gtab input to the "
            b0_s += "IVIM model, you may have provided a gtab with "
            b0_s += "b0_threshold larger than 0. Please initialize the gtab "
            b0_s += "input with b0_threshold=0"
            raise ValueError(b0_s)

        ReconstModel.__init__(self, gtab)
        self.split_b_D = split_b_D
        self.split_b_S0 = split_b_S0
        self.bounds = bounds
        self.two_stage = two_stage
        self.tol = tol
        self.options = {'gtol': gtol, 'ftol': ftol,
                        'eps': eps, 'maxiter': maxiter}
        self.x_scale = x_scale

        self.bounds = bounds or BOUNDS

    @multi_voxel_fitDKI
    def fit(self, data, dki_map):
        """ Fit method of the IvimModelTRR class.
        The fitting takes place in the following steps: Linear fitting for D
        (bvals > `split_b_D` (default: 400)) and store S0_prime. Another linear
        fit for S0 (bvals < split_b_S0 (default: 200)). Estimate f using
        1 - S0_prime/S0. Use non-linear least squares to fit D_star and f.
        We do a final non-linear fitting of all four parameters and select the
        set of parameters which make sense physically. The criteria for
        selecting a particular set of parameters is checking the
        pseudo-perfusion fraction. If the fraction is more than `f_threshold`
        (default: 25%), we will reject the solution obtained from non-linear
        least squares fitting and consider only the linear fit.
        Parameters
        ----------
        data : array
            The measured signal from one voxel. A multi voxel decorator
            will be applied to this fit method to scale it and apply it
            to multiple voxels.
        Returns
        -------
        IvimFit object
        """
        # Get S0_prime and D - parameters assuming a single exponential decay
        # for signals for bvals greater than `split_b_D`
        S0_prime, D = self.estimate_linear_fit(
            data, self.split_b_D, less_than=False)

        # Get S0 and D_star_prime - parameters assuming a single exponential
        # decay for for signals for bvals greater than `split_b_S0`.

        S0, D_star_prime = self.estimate_linear_fit(data, self.split_b_S0,
                                                    less_than=True)
        # Estimate f
        f_guess = 1 - S0_prime / S0

        # Fit f and D_star using leastsq.
        params_f_D_star = [f_guess, D_star_prime]
        f, D_star = self.estimate_f_D_star(params_f_D_star, data, S0, D)
        params_linear = np.array([S0, f, D_star, D])
        # Fit parameters again if two_stage flag is set.
        if self.two_stage:
            params_two_stage = self._leastsq(data, dki_map, params_linear)
            bounds_violated = ~(np.all(params_two_stage >= self.bounds[0]) and
                                (np.all(params_two_stage <= self.bounds[1])))
            
            if bounds_violated:
                warningMsg = "Bounds are violated for leastsq fitting. "
                warningMsg += "Returning parameters from linear fit"
                warnings.warn(warningMsg, UserWarning)
                return IvimFit(self, params_linear)
            else:
                return IvimFit(self, params_two_stage)
        else:
            return IvimFit(self, params_linear)

    def estimate_linear_fit(self, data, split_b, less_than=True):
        """Estimate a linear fit by taking log of data.
        Parameters
        ----------
        data : array
            An array containing the data to be fit
        split_b : float
            The b value to split the data
        less_than : bool
            If True, splitting occurs for bvalues less than split_b
        Returns
        -------
        S0 : float
            The estimated S0 value. (intercept)
        D : float
            The estimated value of D.
        """
        if less_than:
            bvals_split = self.gtab.bvals[self.gtab.bvals <= split_b]
            D, neg_log_S0 = np.polyfit(bvals_split,
                                       -np.log(data[self.gtab.bvals <=
                                                    split_b]), 1)
        else:
            bvals_split = self.gtab.bvals[self.gtab.bvals >= split_b]
            D, neg_log_S0 = np.polyfit(bvals_split,
                                       -np.log(data[self.gtab.bvals >=
                                                    split_b]), 1)

        S0 = np.exp(-neg_log_S0)
        return S0, D

    def estimate_f_D_star(self, params_f_D_star, data, S0, D):
        """Estimate f and D_star using the values of all the other parameters
        obtained from a linear fit.
        Parameters
        ----------
        params_f_D_star: array
            An array containing the value of f and D_star.
        data : array
            Array containing the actual signal values.
        S0 : float
            The parameters S0 obtained from a linear fit.
        D : float
            The parameters D obtained from a linear fit.
        Returns
        -------
        f : float
           Perfusion fraction estimated from the fit.
        D_star :
            The value of D_star estimated from the fit.
        """
        gtol = self.options["gtol"]
        ftol = self.options["ftol"]
        xtol = self.tol
        maxfev = self.options["maxiter"]

        try:
            res = least_squares(f_D_star_error,
                                params_f_D_star,
                                bounds=((0., 0.), (self.bounds[1][1],
                                                   self.bounds[1][2])),
                                args=(self.gtab, data, S0, D),
                                ftol=ftol,
                                xtol=xtol,
                                gtol=gtol,
                                max_nfev=maxfev)
            f, D_star = res.x
            return f, D_star
        except ValueError:
            warningMsg = "x0 obtained from linear fitting is not feasibile"
            warningMsg += " as initial guess for leastsq while estimating "
            warningMsg += "f and D_star. Using parameters from the "
            warningMsg += "linear fit."
            warnings.warn(warningMsg, UserWarning)
            f, D_star = params_f_D_star
            return f, D_star

    def predict(self, ivim_params, gtab, S0=1.):
        """
        Predict a signal for this IvimModel class instance given parameters.
        Parameters
        ----------
        ivim_params : array
            The ivim parameters as an array [S0, f, D_star and D]
        gtab : GradientTable class instance
            Gradient directions and bvalues.
        S0 : float, optional
            This has been added just for consistency with the existing
            API. Unlike other models, IVIM predicts S0 and this is over written
            by the S0 value in params.
        Returns
        -------
        ivim_signal : array
            The predicted IVIM signal using given parameters.
        """
        return ivim_prediction(ivim_params, gtab)

    def _leastsq(self, data, dki_map, x0):
        """Use leastsq to find ivim_params
        Parameters
        ----------
        data : array, (len(bvals))
            An array containing the signal from a voxel.
            If the data was a 3D image of 10x10x10 grid with 21 bvalues,
            the multi_voxel decorator will run the single voxel fitting
            on all the 1000 voxels to get the parameters in
            IvimFit.model_paramters. The shape of the parameter array
            will be (data[:-1], 4).
        x0 : array
            Initial guesses for the parameters S0, f, D_star and D
            calculated using a linear fitting.
        Returns
        -------
        x0 : array
            Estimates of the parameters S0, f, D_star and D.
        """
        gtol = self.options["gtol"]
        ftol = self.options["ftol"]
        xtol = self.tol
        maxfev = self.options["maxiter"]
        bounds = self.bounds

        try:
            res = least_squares(_ivim_error,
                                x0,
                                bounds=bounds,
                                ftol=ftol,
                                xtol=xtol,
                                gtol=gtol,
                                max_nfev=maxfev,
                                args=(self.gtab, data, dki_map),
                                x_scale=self.x_scale)
            ivim_params = res.x
            if np.all(np.isnan(ivim_params)):
                return np.array([-1, -1, -1, -1])
            return ivim_params
        except ValueError:
            warningMsg = "x0 is unfeasible for leastsq fitting."
            warningMsg += " Returning x0 values from the linear fit."
            warnings.warn(warningMsg, UserWarning)
            return x0
            
