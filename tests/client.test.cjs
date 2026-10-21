const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// run the client against a small fake DOM without a wallet or node.
class Element {
  constructor() {this.value="";this.children=[];this.attributes={};this.listeners={};this.className="";this.hidden=false;}
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {this.children=[...nodes];}
  setAttribute(key,value) {this.attributes[key]=value;}
  addEventListener(type,callback) {this.listeners[type]=callback;}
  focus() {}
  get classList() {return {add:name=>{this.className+=` ${name}`;}};}
}
const originalState = () => ({player:"0xabc",round_id:1,board:[],finished:false,verified:false,won:false,passport:{wins:0,verified_rounds:0},receipts:[]});
const tick = () => new Promise(resolve=>setImmediate(resolve));

async function browser(handler) {
  const elements = new Map(), storage = new Map(), calls=[];
  const get = id => {if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  let counter=0;
  const context = vm.createContext({
    document:{getElementById:get,createElement:()=>new Element(),querySelectorAll:()=>[]},
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    crypto:{randomUUID:()=>`request-${String(++counter).padStart(16,"0")}`},
    navigator:{clipboard:{writeText:async()=>{}}},
    fetch:async(url,options)=>{
      calls.push({url,options,body:options.body?JSON.parse(options.body):null});
      let value;
      if(url==="/api/config")value={ready:true,words:["asset","chain","peers"],deployment:{}};
      else if(url==="/api/state")value=originalState();
      else value=await handler(url,options);
      return {ok:true,json:async()=>value};
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../static/app.js"),"utf8"),context);
  await tick();
  return {context,get,storage,calls,run:code=>vm.runInContext(code,context)};
}

test("a lost guess response reuses its saved request identity",async()=>{
  let submissions=0;
  const ui=await browser(async(url)=>{
    assert.equal(url,"/api/guess");
    if(++submissions===1)throw new TypeError("network failure");
    return {...originalState(),board:[{word:"asset",feedback:[0,0,0,0,0]}]};
  });
  ui.get("guess-input").value="asset";
  await ui.run("submitGuess()");
  assert.equal(ui.get("guess-input").value,"asset");
  assert.ok(ui.storage.has("blockword_pending_guess"));
  assert.match(ui.get("status").textContent,/Connection lost/);
  await ui.run("submitGuess()");
  const sent=ui.calls.filter(call=>call.url==="/api/guess");
  assert.equal(sent.length,2);
  assert.equal(sent[0].body.request_id,sent[1].body.request_id);
  assert.equal(sent[1].body.expected_attempt,1);
  assert.equal(ui.get("guess-input").value,"");
  assert.equal(ui.storage.has("blockword_pending_guess"),false);
});

test("explicit verification preserves a draft and uses POST recovery",async()=>{
  const ui=await browser(async(url,options)=>{
    assert.equal(url,"/api/recover");assert.equal(options.method,"POST");return originalState();
  });
  ui.get("guess-input").value="chain";
  ui.get("refresh-button").listeners.click();
  await tick();
  assert.equal(ui.get("guess-input").value,"chain");
  assert.ok(ui.calls.some(call=>call.url==="/api/recover"));
});

test("client startup reads state without requesting recovery",async()=>{
  const ui=await browser(async()=>assert.fail("Startup must not post an action"));
  assert.deepEqual(ui.calls.map(call=>call.url),["/api/config","/api/state"]);
});

test("letter feedback has spoken meanings instead of internal CSS names",async()=>{
  const ui=await browser(async()=>({...originalState(),board:[{word:"asset",feedback:[2,1,0,0,0]}]}));
  ui.get("guess-input").value="asset";
  await ui.run("submitGuess()");
  const firstRow=ui.get("board").children[0];
  assert.equal(firstRow.children[0].attributes.role,"cell");
  assert.equal(firstRow.children[0].attributes["aria-label"],"A, correct position");
  assert.match(ui.get("board-announcement").textContent,/S, in another position/);
  assert.match(firstRow.children[2].attributes["aria-label"],/no unused copy/);
});
