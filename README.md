# IVIMKurtosis

A implementation of IVIM-Kurtosis Model on Dipy source.

Requirements:
- Dipy>=1.4.1


## Example 

    python setup.py install
    
    from kurtosis.kurtosis import IvimModel

Have just one difference between this implementation and the IVIM from dipy.

    ivimfit = ivimmodel.fit(data, dki_map)


Dipy Reference:

E. Garyfallidis, M. Brett, B. Amirbekian, A. Rokem, S. Van Der Walt, M. Descoteaux, I. Nimmo-Smith and DIPY contributors, "DIPY, a library for the analysis of diffusion MRI data", Frontiers in Neuroinformatics, vol. 8, p. 8, Frontiers, 2014.
