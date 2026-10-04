"""Focused proof for convolution decay, effect tails, pitch and safe model inference."""
import numpy as np
from effects import RATE, impulse, spatial, render_effects, vocal_dynamics, estimate, MODEL, _load_model, _predict, CHARACTER_MODES


def main():
    ir = impulse(RATE, 1.2)
    assert np.count_nonzero(ir) > RATE, 'reverb must have a dense field, not a handful of taps'
    assert not np.allclose(ir[:,0],ir[:,1]), 'stereo tails must be decorrelated'
    early=np.sqrt(np.mean(ir[int(.1*RATE):int(.3*RATE)]**2))
    late=np.sqrt(np.mean(ir[int(.8*RATE):int(1*RATE)]**2))
    assert late < early*.1, 'late field should decay'
    voice=np.zeros(RATE*5,np.float32);voice[4*RATE-1000]=.3
    blocks=[dict(room=.2,decay=1,delay_wet=.2,delay=.28,width=.4)]*2
    wet=render_effects(voice,np.zeros(len(voice)),blocks)
    assert np.max(abs(wet[4*RATE:])) > .001, 'tails must survive the block boundary'
    assert np.isfinite(wet).all()
    t=np.arange(RATE*2)/RATE
    sine=(.35*np.sin(2*np.pi*220*t)).astype(np.float32)
    processed=vocal_dynamics(sine)
    for mode in CHARACTER_MODES:
        output=render_effects(sine,np.zeros(len(sine)),[],mode)
        assert output.shape==(len(sine),2), mode
        assert np.isfinite(output).all() and np.max(abs(output))<1, mode
        assert not np.allclose(output,sine[:,None]*.5), mode
        silent=render_effects(np.zeros(1000,np.float32),np.zeros(1000),[],mode)
        assert not np.any(silent), mode
    dominant=np.fft.rfftfreq(len(sine),1/RATE)[np.argmax(abs(np.fft.rfft(processed)))]
    assert abs(dominant-220)<1, 'dynamics must not lower the voice register'
    assert np.max(abs(processed)) <= np.max(abs(sine))+.001
    assert estimate(np.zeros((RATE,2),np.float32))['room']==0
    if MODEL.exists():
        model=_load_model(MODEL.stat().st_mtime_ns)
        assert model['value'].shape[1]==4
        assert all(model['left'][root]>=0 for root in model['roots'])
        assert np.isfinite(_predict(np.zeros(53),model)).all()
    print('Dense stereo decay, cross-block tails, dynamics pitch safety and numeric model inference passed')


if __name__=='__main__':main()
