"""Alignment audit and detail-preserving correspondence candidates.

No reference image enters these methods. Geometric disparity describes the
requested camera transform; optical flow describes the generated appearance.
They are deliberately distinguished rather than assumed identical.
"""
from __future__ import annotations

import cv2
import numpy as np
from cvdc_refined import high_pass


def sample(image, map_x, map_y, interpolation=cv2.INTER_CUBIC):
    return cv2.remap(image,map_x.astype(np.float32),map_y.astype(np.float32),interpolation,
                     borderMode=cv2.BORDER_REFLECT101)


def visibility_map_from_depth(disparity):
    """Invert horizontal source projection using subpixel splat and z-buffer.

    Returns target-to-source coordinates and occupancy, not hole-filled flow.
    Samples with the largest disparity win a target collision.
    """
    height,width=disparity.shape
    yy,xx=np.mgrid[:height,:width].astype(np.float32)
    tx=xx-disparity
    x0=np.floor(tx).astype(np.int32);frac=tx-x0
    target_indices=[];source_positions=[];depths=[];weights=[]
    for offset,weight in [(0,1-frac),(1,frac)]:
        xt=x0+offset
        valid=np.isfinite(disparity)&(xt>=0)&(xt<width)&(weight>1e-6)
        target_indices.append((yy.astype(np.int32)[valid]*width+xt[valid]).ravel())
        source_positions.append(xx[valid]);depths.append(disparity[valid]);weights.append(weight[valid])
    ids=np.concatenate(target_indices);xs=np.concatenate(source_positions)
    ds=np.concatenate(depths);ws=np.concatenate(weights)
    front=np.full(height*width,-np.inf,np.float32);np.maximum.at(front,ids,ds)
    winner=ds>=front[ids]-.25
    numerator=np.bincount(ids[winner],weights=xs[winner]*ws[winner],minlength=height*width)
    denominator=np.bincount(ids[winner],weights=ws[winner],minlength=height*width)
    valid=denominator.reshape(height,width)>.25
    mapping=(numerator/np.maximum(denominator,1e-8)).reshape(height,width).astype(np.float32)
    mapping=np.where(valid,mapping,xx)
    return mapping,valid


def horizontal_local_refine(source,baseline,initial_x,radius=2):
    """Epipolar constrained matching around a source-only appearance estimate."""
    h,w=source.shape[:2];yy,xx=np.mgrid[:h,:w].astype(np.float32)
    src=cv2.cvtColor(source,cv2.COLOR_RGB2GRAY).astype(np.float32)/255
    dst=cv2.cvtColor(baseline,cv2.COLOR_RGB2GRAY).astype(np.float32)/255
    # Match mid-band structure instead of raw brightness. This is only a local
    # appearance correspondence, not metric depth recovery.
    src=src-cv2.GaussianBlur(src,(0,0),3)
    dst=dst-cv2.GaussianBlur(dst,(0,0),3)
    offsets=np.arange(-radius,radius+1,dtype=np.float32)
    costs=[]
    for off in offsets:
        warped=sample(src,initial_x+off,yy)
        costs.append(cv2.boxFilter(np.minimum(np.abs(warped-dst),.15),-1,(7,5),normalize=True))
    costs=np.stack(costs)
    idx=np.argmin(costs,axis=0)
    idx0=np.maximum(idx-1,0);idx2=np.minimum(idx+1,len(offsets)-1)
    c0=np.take_along_axis(costs,idx0[None],axis=0)[0]
    c1=np.take_along_axis(costs,idx[None],axis=0)[0]
    c2=np.take_along_axis(costs,idx2[None],axis=0)[0]
    sub=np.clip(.5*(c0-c2)/np.maximum(c0-2*c1+c2,1e-7),-.5,.5)
    sub=np.where((idx>0)&(idx<len(offsets)-1),sub,0)
    adjustment=offsets[idx]+sub
    adjustment=cv2.medianBlur(adjustment.astype(np.float32),3)
    return initial_x+adjustment


def prepare_alignment(source,baseline,disparity=None):
    h,w=source.shape[:2];yy,xx=np.mgrid[:h,:w].astype(np.float32)
    dis=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    src_gray=cv2.cvtColor(source,cv2.COLOR_RGB2GRAY)
    dst_gray=cv2.cvtColor(baseline,cv2.COLOR_RGB2GRAY)
    backward=dis.calc(dst_gray,src_gray,None)
    forward=dis.calc(src_gray,dst_gray,None)
    fx,fy=xx+backward[...,0],yy+backward[...,1]
    reverse=sample(forward,fx,fy,cv2.INTER_LINEAR)
    fb=np.linalg.norm(backward+reverse,axis=2)
    full_valid=(fx>=2)&(fx<w-3)&(fy>=2)&(fy<h-3)
    # Occlusion uncertainty does not attenuate every reliable pixel. Gate only
    # clear cycle failures; keep continuous gain in the supported regions.
    gate=full_valid.astype(np.float32)*np.clip((3-fb)/2,0,1)
    flow_rgb=sample(source.astype(np.float32)/255,fx,fy)
    flow_h=flow_rgb-cv2.GaussianBlur(flow_rgb,(0,0),1)
    source_high=high_pass(source);base_high=high_pass(baseline)
    warped_high=sample(source_high,fx,fy)
    horizontal_rgb=sample(source.astype(np.float32)/255,fx,yy)
    horizontal_h=horizontal_rgb-cv2.GaussianBlur(horizontal_rgb,(0,0),1)
    refined_x=horizontal_local_refine(source,baseline,fx)
    refined_rgb=sample(source.astype(np.float32)/255,refined_x,yy)
    refined_h=refined_rgb-cv2.GaussianBlur(refined_rgb,(0,0),1)
    # Bounded local RMS restoration counteracts interpolation attenuation.
    src_energy=sample(cv2.GaussianBlur(np.mean(source_high**2,axis=2),(0,0),2),fx,fy)
    mapped_energy=cv2.GaussianBlur(np.mean(flow_h**2,axis=2),(0,0),2)
    # Cubic interpolation can undershoot a nonnegative energy field.
    gain=np.clip(np.sqrt(np.maximum(src_energy,0)/np.maximum(mapped_energy,1e-8)),1,1.5)
    out={'source_high':source_high,'base_high':base_high,'warp_high_cubic':warped_high,
         'flow_rgb_high':flow_h,'flow_gain_high':flow_h*gain[...,None],
         'horizontal_high':horizontal_h,'refined_horizontal_high':refined_h,
         'horizontal_x':fx,'grid_y':yy,
         'flow_gate':gate,'valid':full_valid.astype(np.float32),
         'backward':backward,'fb_error':fb,'gain':gain,
         'diagnostics':{'flow_dx_median':float(np.median(backward[...,0])),
                        'flow_dy_median':float(np.median(backward[...,1])),
                        'cycle_error_median':float(np.median(fb)),
                        'gate_mean':float(gate.mean()),
                        'cubic_warp_high_rms_ratio':float(np.sqrt(np.mean(warped_high**2)/max(np.mean(source_high**2),1e-10))),
                        'warp_rgb_then_high_rms_ratio':float(np.sqrt(np.mean(flow_h**2)/max(np.mean(source_high**2),1e-10)))}}
    if disparity is not None:
        dx,valid=visibility_map_from_depth(disparity)
        depth_rgb=sample(source.astype(np.float32)/255,dx,yy)
        depth_h=depth_rgb-cv2.GaussianBlur(depth_rgb,(0,0),1)
        out['depth_high']=depth_h;out['depth_gate']=cv2.erode(valid.astype(np.uint8),np.ones((3,3),np.uint8)).astype(np.float32)
        out['diagnostics']['depth_disp_median']=float(np.median(disparity))
        out['diagnostics']['depth_vs_appearance_median_abs']=float(np.median(np.abs((dx-xx)-backward[...,0])[valid])) if valid.any() else None
    return out


def aligned_compensate(baseline,prepared,band='flow_rgb_high',alpha=.6,beta=.1,gate='valid'):
    if band not in prepared or gate not in prepared:raise ValueError('Missing requested alignment data')
    confidence=prepared[gate]
    correction=alpha*prepared[band]-beta*prepared['base_high']
    # On unsupported regions keep the generated output, never paste an
    # unaligned source residual as a hidden fallback.
    result=baseline.astype(np.float32)+255*confidence[...,None]*correction
    return np.rint(np.clip(result,0,255)).astype(np.uint8)


def fit_generated_depth_mapping(disparity,prepared):
    """Fit one affine convergence transform from L--B correspondence, no GT.

    The result aligns to the generator's apparent view. It is not physical
    camera calibration, and cannot repair incorrect geometry already in B.
    """
    h,w=disparity.shape;yy,xx=np.mgrid[:h,:w].astype(np.float32)
    fx=xx+prepared['backward'][...,0];fy=yy+prepared['backward'][...,1]
    depth_at_source=sample(disparity,fx,fy,cv2.INTER_LINEAR)
    flow=prepared['backward'][...,0]
    valid=(prepared['valid']>0)&(prepared['fb_error']<1)&(np.abs(prepared['backward'][...,1])<1)
    values=depth_at_source[valid];target=flow[valid]
    if len(values)<200:
        return disparity.copy(),{'valid_fit':False,'reference_used':False}
    values=values[::4];target=target[::4]
    X=np.column_stack([values,np.ones_like(values)])
    coeff=np.linalg.lstsq(X,target,rcond=None)[0]
    unconstrained=coeff.copy()
    for _ in range(5):
        residual=target-X@coeff
        scale=max(float(np.median(np.abs(residual)))*1.4826,.25)
        weights=np.minimum(1,1.5*scale/np.maximum(np.abs(residual),1e-6))
        coeff=np.linalg.lstsq(X*np.sqrt(weights[:,None]),target*np.sqrt(weights),rcond=None)[0]
        coeff[0]=np.clip(coeff[0],0,2)
        coeff[1]=np.clip(coeff[1],-64,64)
    fitted=coeff[0]*disparity+coeff[1]
    stats={'valid_fit':True,'slope_relative_to_fixed48':float(coeff[0]),
           'convergence_offset_px':float(coeff[1]),'unconstrained_slope':float(unconstrained[0]),
           'fit_mae_px':float(np.mean(np.abs(target-X@coeff))),
           'matched_pixels':int(valid.sum()),'reference_used':False}
    return fitted.astype(np.float32),stats


def prepare_calibrated_depth(source,baseline,disparity,prepared=None):
    prepared=prepare_alignment(source,baseline) if prepared is None else prepared
    fitted,stats=fit_generated_depth_mapping(disparity,prepared)
    map_x,valid=visibility_map_from_depth(fitted)
    yy=np.mgrid[:baseline.shape[0],:baseline.shape[1]][0].astype(np.float32)
    warped=sample(source.astype(np.float32)/255,map_x,yy)
    prepared['calibrated_depth_high']=warped-cv2.GaussianBlur(warped,(0,0),1)
    gate=cv2.erode(valid.astype(np.uint8),np.ones((3,3),np.uint8)).astype(np.float32)
    if not stats['valid_fit']:gate[:]=0
    prepared['calibrated_depth_gate']=gate
    prepared['depth_calibration']=stats
    return prepared
