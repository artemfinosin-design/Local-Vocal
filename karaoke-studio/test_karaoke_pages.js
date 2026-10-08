const assert=require('node:assert/strict');
const {karaokePages}=require('./karaoke-pages.js');
const words=('I wanna sing every single word without losing I or the timing '.repeat(4)).trim().split(' ').map((text,i)=>({text,start:i*.2,end:(i+1)*.2}));
const pages=karaokePages([{words}]);
assert.deepEqual(pages.flatMap(page=>page.words),words);
assert.ok(pages.every(page=>page.words.length<=8));
assert.ok(pages.every(page=>page.start===page.words[0].start&&page.end===page.words.at(-1).end));
assert.deepEqual(karaokePages([]),[]);
console.log('Karaoke pages: every word, timing, compact pages passed');
