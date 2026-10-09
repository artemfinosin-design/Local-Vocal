const assert=require('node:assert/strict');
const {playbackPosition}=require('./players.js');
assert.deepEqual(playbackPosition(4,8),{total:8,current:4,progress:50});
assert.deepEqual(playbackPosition(20,8),{total:8,current:8,progress:100});
assert.deepEqual(playbackPosition(-1,8),{total:8,current:0,progress:0});
assert.deepEqual(playbackPosition(4,NaN),{total:0,current:0,progress:0});
assert.deepEqual(playbackPosition(Infinity,0),{total:0,current:0,progress:0});
console.log('Player: seeking bounds and unavailable metadata passed');
