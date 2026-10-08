/* Short pages preserve every word and its existing timing. */
function karaokePages(lines){
  const pages=[];
  for(const line of lines){
    let words=[],characters=0;
    const flush=()=>{if(words.length)pages.push({start:words[0].start,end:words.at(-1).end,words});words=[];characters=0;};
    for(const word of line.words){
      if(words.length&&(words.length>=8||characters+word.text.length>60))flush();
      words.push(word);characters+=word.text.length+1;
    }
    flush();
  }
  return pages;
}
if(typeof module!=='undefined')module.exports={karaokePages};
