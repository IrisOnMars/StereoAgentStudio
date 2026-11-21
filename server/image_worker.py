"""Deterministic, bounded image tools. Receives one JSON request over stdin."""
import json, sys
from pathlib import Path
from PIL import Image, ImageOps, ImageEnhance

Image.MAX_IMAGE_PIXELS = 40_000_000
def number(value, name, low, high, integer=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not low <= value <= high:
        raise ValueError(f'{name} must be between {low} and {high}')
    if integer and int(value) != value: raise ValueError(f'{name} must be an integer')
    return int(value) if integer else value

def process(req):
    source=Path(req['source']); target=Path(req['target']); params=req.get('params',{})
    with Image.open(source) as opened:
        image=ImageOps.exif_transpose(opened)
        image.load()
        if image.width*image.height>40_000_000: raise ValueError('Image exceeds 40 megapixels')
        image=image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
    original=image.size; tool=req['tool']
    if tool=='crop_image':
        left,top,right,bottom=[number(params.get(k,0),k,0,40000,True) for k in ('left','top','right','bottom')]
        if left+right>=image.width or top+bottom>=image.height: raise ValueError('Crop would remove the entire image')
        image=image.crop((left,top,image.width-right,image.height-bottom))
    elif tool=='resize_image':
        width=number(params.get('width'),'width',1,8192,True)
        height=params.get('height')
        height=number(height,'height',1,8192,True) if height is not None else max(1,round(image.height*width/image.width))
        if width*height>40_000_000 or height>8192: raise ValueError('Requested dimensions are too large')
        image=image.resize((width,height),Image.Resampling.LANCZOS)
    elif tool=='adjust_color':
        for key,enhancer in [('saturation',ImageEnhance.Color),('brightness',ImageEnhance.Brightness),('contrast',ImageEnhance.Contrast)]:
            if key in params:image=enhancer(image).enhance(number(params[key],key,0,3))
    elif tool=='rotate_image':
        angle=number(params.get('degrees'),'degrees',-360,360)
        image=image.rotate(-angle,expand=True,resample=Image.Resampling.BICUBIC)
    elif tool=='export_image':
        fmt=params.get('format','png').lower()
        if fmt not in ('png','jpg','webp'): raise ValueError('Unsupported export format')
    elif tool!='import_image':raise ValueError('Unknown image tool')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.suffix.lower() in ('.jpg','.jpeg'):image=image.convert('RGB')
    image.save(target,quality=95)
    thumb=image.convert('RGB');thumb.thumbnail((768,768));thumbnail=target.with_suffix('.preview.jpg');thumb.save(thumbnail,quality=85)
    with Image.open(target) as verify:
        verify.load()
        if verify.size!=image.size:raise ValueError('Output dimension verification failed')
    return {'width':image.width,'height':image.height,'format':target.suffix[1:],'thumbnail':str(thumbnail),'checks':{'decoded':True,'dimensions_verified':True},'sourceSize':list(original)}

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:print(json.dumps({'ok':True,**process(json.load(sys.stdin))}))
    except Exception as exc:print(json.dumps({'ok':False,'error':str(exc)}));sys.exit(1)
