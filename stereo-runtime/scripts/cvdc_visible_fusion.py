"""Experimental confidence-weighted reuse of visible source appearance.

The input pair is L and generated B. No ground-truth right image is accepted.
This follows B's apparent view and does not calibrate a physical stereo camera.
"""
from __future__ import annotations
import cv2
import numpy as np
from cvdc_alignment_v3 import sample


def prepare_visible_fusion(source,baseline):
    if source.shape!=baseline.shape or source.ndim!=3 or source.shape[2]!=3:
        raise ValueError('source and baseline must have matching RGB dimensions')
    h,w=source.shape[:2];yy,xx=np.mgrid[:h,:w].astype(np.float32)
    dis=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    left_gray=cv2.cvtColor(source,cv2.COLOR_RGB2GRAY)
    base_gray=cv2.cvtColor(baseline,cv2.COLOR_RGB2GRAY)
    backward=dis.calc(base_gray,left_gray,None)
    forward=dis.calc(left_gray,base_gray,None)
    sx=xx+backward[...,0]
    # Rectified stereo assumption: sample the same row, even if generic flow
    # reports small vertical drift. Recompute its cycle check on that map.
    returned=sample(forward,sx,yy,cv2.INTER_LINEAR)
    cycle=np.abs(backward[...,0]+returned[...,0])
    inside=(sx>=3)&(sx<=w-4)
    valid=inside&(cycle<1.5)&(np.abs(backward[...,1])<1.5)
    # Use B directly in unsupported regions. Erode only uncertainty borders.
    valid=cv2.erode(valid.astype(np.uint8),np.ones((3,3),np.uint8)).astype(np.float32)
    aligned=sample(source.astype(np.float32)/255,sx,yy)
    base=baseline.astype(np.float32)/255
    difference=np.mean(np.abs(cv2.GaussianBlur(aligned,(0,0),1.5)-cv2.GaussianBlur(base,(0,0),1.5)),axis=2)
    # Reliability is based on the observed pair only. It is not a proof that a
    # region is physically co-visible. Reject clearly inconsistent appearances.
    confidence=valid*np.exp(-.5*(difference/.08)**2)*np.exp(-.5*(cycle/.75)**2)
    return {'aligned':aligned,'source':source.astype(np.float32)/255,'base':base,
            'confidence':confidence,'difference':difference,'cycle_error':cycle,
            'valid':valid,'source_x':sx}


def fuse_visible(baseline,prepared,strength=.5,mode='rgb',aligned=True):
    if not 0<=strength<=1:raise ValueError('strength must lie between 0 and 1')
    source=prepared['aligned'] if aligned else prepared['source']
    base=prepared['base']
    if mode=='rgb':correction=source-base
    elif mode=='bounded_rgb':correction=np.clip(source-base,-16/255,16/255)
    elif mode=='high':
        correction=(source-cv2.GaussianBlur(source,(0,0),1))-(base-cv2.GaussianBlur(base,(0,0),1))
    else:raise ValueError('unknown mode')
    result=baseline.astype(np.float32)+255*strength*prepared['confidence'][...,None]*correction
    return np.rint(np.clip(result,0,255)).astype(np.uint8)
