const assert=require('node:assert/strict');
const {detectNote,noteDistance}=require('./note-guide.js');
const rate=12000;
for(const frequency of [82.41,220,440,880]){
  const wave=Float32Array.from({length:2048},(_,i)=>.2*Math.sin(2*Math.PI*frequency*i/rate));
  assert.ok(Math.abs(detectNote(wave,rate)-(69+12*Math.log2(frequency/440)))<.08);
}
assert.equal(detectNote(new Float32Array(2048),rate),null);
let seed=73;const noise=Float32Array.from({length:2048},()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296-.5;});
assert.equal(detectNote(noise,rate),null);
assert.equal(noteDistance(48,72),0);assert.ok(Math.abs(noteDistance(59.9,60.1)-.2)<1e-6);
console.log('Pitch: four registers, silence, noise, octave matching passed');
