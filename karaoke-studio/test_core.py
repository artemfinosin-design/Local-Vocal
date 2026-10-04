"""Run with python test_core.py after installing numpy."""

import tempfile
from pathlib import Path

import numpy as np

import app
from audio_core import RATE, analyze, mix, read_wav, save_meta, write_wav


def main():
    length = RATE * 2
    t = np.arange(length) / RATE
    vocal = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    original = np.column_stack((vocal * 0.2, vocal))
    instrumental = np.zeros((length, 2), np.float32)
    meta = analyze(original)
    assert np.mean(meta["profiles"]["vocals"]["pan"]) > 0.5, "right-channel voice should pan right"
    assert not any(role["id"] == "backing" for role in meta["roles"]), "panning alone is not evidence of another singer"
    replacement = (0.1 * np.sin(2 * np.pi * 233 * t[:RATE])).astype(np.float32)
    result = mix(instrumental, {"vocals": original}, [(replacement, 0.5, "lead")], meta)
    assert np.max(np.abs(result[:int(RATE * 0.4)])) < 1e-5, "offset should preserve initial silence"
    assert np.sqrt(np.mean(result[:, 1] ** 2)) > np.sqrt(np.mean(result[:, 0] ** 2)) * 2
    stable = result[int(RATE * 0.7):int(RATE * 1.3), 1]
    frequencies = np.fft.rfftfreq(len(stable), 1 / RATE)
    frequency = frequencies[np.argmax(np.abs(np.fft.rfft(stable * np.hanning(len(stable)))))]
    assert abs(frequency - 220) < 5, "notes should move toward the original without a manual pitch setting"
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "result.wav"
        write_wav(path, result)
        loaded = read_wav(path)
        assert loaded.shape == result.shape
        assert np.max(np.abs(loaded - result)) < 1 / 32768 + 1e-5
        old_data = app.DATA
        app.DATA = Path(temp)
        job_id = "a" * 32
        folder = app.DATA / job_id
        folder.mkdir()
        write_wav(folder / "vocals.wav", original)
        write_wav(folder / "instrumental.wav", instrumental)
        save_meta(folder / "analysis.json", meta)
        app.jobs[job_id] = {"version": 2, "state": "ready", "tracks": [], "renders": [], "markers": [],
                            "roles": [{key: value for key, value in role.items() if key != "mask"} for role in meta["roles"]], "duration": 2}
        app.save_job(job_id)
        app.jobs.clear()
        app.restore_jobs()
        assert app.jobs[job_id]["state"] == "ready", "finished project should survive restart"
        app.jobs.clear()
        app.DATA = old_data
    long_time = np.arange(RATE * 12) / RATE
    one = 0.15 * np.sin(2 * np.pi * 180 * long_time)
    two = 0.12 * (np.sin(2 * np.pi * 310 * long_time) + 0.5 * np.sin(2 * np.pi * 620 * long_time))
    phrase = np.where(long_time < 8, one, two).astype(np.float32)
    voices = analyze(np.column_stack((phrase, phrase)))
    assert not any(role["id"] == "artist2" for role in voices["roles"]), "a short register change is not evidence of another singer"
    background = np.zeros_like(original)
    background[RATE // 4:7 * RATE // 4] = original[RATE // 4:7 * RATE // 4] * 0.5
    layered = analyze(original, background)
    assert any(role["id"] == "backing" for role in layered["roles"])
    assert "backing" in layered["profiles"], "background loudness must use its own reference"
    print("Automatic audio and persistence checks passed")


if __name__ == "__main__":
    main()
