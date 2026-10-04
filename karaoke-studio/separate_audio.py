"""Run both learned separators in an isolated process; files never leave the device."""

import logging
import json
import sys
from pathlib import Path
import numpy as np

from runtime import configure_decoder

SEPARATION_VERSION = 2


def split_mdx(samples, model):
    """Keep both stems in the input's scale; subtraction must use the same vocal."""
    samples=np.asarray(samples,np.float32)
    if samples.ndim!=2 or samples.shape[1]!=2 or not len(samples) or not np.isfinite(samples).all():
        raise ValueError('Некорректное аудио для разделения')
    peak=float(np.max(abs(samples)))
    if peak<1e-8:return np.zeros_like(samples),np.zeros_like(samples)
    normalized=np.ascontiguousarray((samples/peak).T)
    try:
        primary=np.asarray(model.demix(normalized),np.float32).T*float(model.compensate)*peak
        if primary.shape!=samples.shape or not np.isfinite(primary).all():
            raise RuntimeError('Модель вернула некорректную дорожку')
        if model.primary_stem_name=='Vocals':return primary,samples-primary
        if model.primary_stem_name=='Instrumental':return samples-primary,primary
        raise RuntimeError('Модель не поддерживает разделение вокала и инструментала')
    finally:
        model.clear_gpu_cache()


def separate(song, output, models):
    configure_decoder()
    from audio_separator.separator import Separator
    from audio_core import read_wav,write_wav

    separator = Separator(output_dir=str(output), model_file_dir=str(models),
                          output_format="WAV", use_soundfile=True,
                          normalization_threshold=1.0, log_level=logging.WARNING,
                          mdx_params={"hop_length": 1024, "segment_size": 256,
                                      "overlap": 0.25, "batch_size": 1, "enable_denoise": False})
    separator.load_model(model_filename="UVR-MDX-NET-Voc_FT.onnx")
    original=read_wav(song)
    vocals,instrumental=split_mdx(original,separator.model_instance)
    separator.load_model(model_filename="UVR_MDXNET_KARA_2.onnx")
    lead,backing=split_mdx(vocals,separator.model_instance)
    stems=dict(vocals=vocals,instrumental=instrumental,lead=lead,backing=backing)
    # One common export gain preserves subtraction and avoids independently clipped stems.
    peak=max(float(np.max(abs(stem))) for stem in stems.values())
    gain=min(1.,.98/max(peak,1e-8))
    for name,stem in stems.items():write_wav(output/(name+'.wav'),stem*gain)
    (output/'separation.json').write_text(json.dumps(dict(version=SEPARATION_VERSION,gain=gain,source_peak=float(np.max(abs(original))))),encoding='utf-8')
    for name in ("vocals", "instrumental", "lead", "backing"):
        if not (output / (name + ".wav")).is_file():
            raise RuntimeError("Модель не создала дорожку: " + name)


if __name__ == "__main__":
    separate(*(Path(argument).resolve() for argument in sys.argv[1:4]))
