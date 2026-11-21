"""Experimental geometry-supported, frequency-separated source reconstruction.

No reference right image is accepted. The geometry branch fits the apparent
view of B; it is not metric camera calibration or proof of physical visibility.
"""
from __future__ import annotations
import cv2
import numpy as np
from cvdc_visible_fusion import prepare_visible_fusion
from cvdc_alignment_v3 import (prepare_alignment,fit_generated_depth_mapping,
                                visibility_map_from_depth,sample)


def frequency_bands(image):
    fine_low=cv2.GaussianBlur(image,(0,0),1)
    coarse_low=cv2.GaussianBlur(image,(0,0),3)
    return coarse_low,fine_low-coarse_low,image-fine_low


def prepare_multiband(source,baseline,disparity=None):
    data=prepare_visible_fusion(source,baseline)
    data['flow_aligned']=data['aligned'];data['flow_confidence']=data['confidence']
    if disparity is not None:
        p=prepare_alignment(source,baseline)
        fitted,diagnostics=fit_generated_depth_mapping(disparity,p)
        map_x,occupancy=visibility_map_from_depth(fitted)
        yy=np.mgrid[:source.shape[0],:source.shape[1]][0].astype(np.float32)
        aligned=sample(source.astype(np.float32)/255,map_x,yy)
        support=cv2.erode(occupancy.astype(np.uint8),np.ones((3,3),np.uint8)).astype(np.float32)
        low_error=np.mean(np.abs(cv2.GaussianBlur(aligned,(0,0),1.5)-cv2.GaussianBlur(data['base'],(0,0),1.5)),axis=2)
        confidence=support*np.exp(-.5*(low_error/.08)**2)
        # An invalid/nonpositive fit cannot establish a usable depth ordering.
        if not diagnostics['valid_fit'] or diagnostics.get('slope_relative_to_fixed48',0)<=.02:
            confidence[:]=0
        data['depth_aligned']=aligned;data['depth_confidence']=confidence
        data['depth_fit']=diagnostics;data['depth_occupancy']=support
    data['base_bands']=frequency_bands(data['base'])
    return data


def multiband_reconstruct(baseline,prepared,alignment='flow',low=.5,mid=.5,
                          high=.8,high_mode='replace'):
    if alignment not in ['flow','depth']:raise ValueError('unknown alignment')
    if any(not 0<=v<=1.5 for v in [low,mid,high]):raise ValueError('invalid band strength')
    a0,a1,a2=frequency_bands(prepared[f'{alignment}_aligned'])
    b0,b1,b2=prepared['base_bands']
    if high_mode=='replace':detail=high*(a2-b2)
    elif high_mode=='add':detail=high*a2
    else:raise ValueError('unknown high-band rule')
    correction=low*(a0-b0)+mid*(a1-b1)+detail
    confidence=prepared[f'{alignment}_confidence']
    output=baseline.astype(np.float32)+255*confidence[...,None]*correction
    return np.rint(np.clip(output,0,255)).astype(np.uint8)
