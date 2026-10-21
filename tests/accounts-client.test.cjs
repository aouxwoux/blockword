const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");

class Element {
  constructor(){this.children=[];this.listeners={};this.value="";this.classes=new Set();this.className="";this.hidden=false;}
  append(...values){this.children.push(...values);}
  replaceChildren(...values){this.children=[...values];}
  addEventListener(name,callback){this.listeners[name]=callback;}
  querySelectorAll(){return [];}
  showModal(){this.open=true;}
  close(){this.open=false;}
  get classList(){return {toggle:(name,enabled)=>enabled?this.classes.add(name):this.classes.delete(name)};}
}

async function page(options={}){
  const elements=new Map(),calls=[];
  const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const profile={display_name:"Player One",wallet_address:"0xabc",linked_demo_accounts:0};
  const wallet={name:"Test wallet",features:{
    "aptos:connect":{connect:async()=>{calls.push({url:"wallet:connect"});return {status:"Approved",args:{address:{toString:()=>"0xabc"},publicKey:{toString:()=>options.key||"0x"+"11".repeat(32)}}};}},
    "aptos:network":{network:async()=>({chainId:options.chainId||249})},
    "aptos:signMessage":{signMessage:async(input)=>{calls.push({url:"wallet:signMessage",input});return {status:options.rejected?"Rejected":"Approved",args:{signature:{toString:()=>"0x"+"22".repeat(64)},fullMessage:`APTOS\nnonce: ${input.nonce}\nmessage: ${input.message}`}};}},
  }};
  let signedIn=false;
  const registry={get:()=>options.noWallet?[]:[wallet],on:()=>{}};
  const context=vm.createContext({document:{getElementById:get,createElement:()=>new Element()},getWallets:()=>registry,
    fetch:async(url,request)=>{
      calls.push({url,request});
      let value,status=200;
      if(url==="/api/account/me"&&request.method==="GET") {value=signedIn&&!options.expired?profile:{detail:"Sign in again"};if(!signedIn||options.expired)status=401;}
      else if(url==="/api/auth/challenge")value={challenge_id:"challenge",chain_id:249,sign_message:{message:"Blockword sign-in",nonce:"nonce",address:false,application:false,chainId:false}};
      else if(url==="/api/auth/verify"){signedIn=true;value={player:profile};}
      else if(url==="/api/account/sessions")value={items:[]};
      else if(url==="/api/account/rounds?limit=20")value={items:[]};
      else if(url==="/api/auth/logout-all"){signedIn=false;value={signed_out:true};}
      else if(url==="/api/account/me"&&request.method==="PATCH"){profile.display_name=JSON.parse(request.body).display_name;value=profile;}
      else throw new Error(`Unexpected account call: ${url}`);
      return {ok:status===200,status,json:async()=>value};
    }});
  // stub the ESM wallet registry and run the account code as-is.
  const source=fs.readFileSync(path.join(__dirname,"../static/accounts.mjs"),"utf8").replace(/^import[^\n]*\n/,"");
  vm.runInContext(source,context);
  await new Promise(resolve=>setImmediate(resolve));
  return {get,calls,profile,open:async()=>{await get("account-button").listeners.click();},
    connect:async()=>{await get("wallet-choices").children[0].listeners.click();}};
}

test("opening the page never prompts a wallet or signs a transaction",async()=>{
  const ui=await page();
  assert.deepEqual(ui.calls.map(call=>call.url),["/api/account/me"]);
  assert.equal(ui.get("account-guest").hidden,false);
});

test("sign-in uses a wallet message and shows the player profile",async()=>{
  const ui=await page();await ui.open();await ui.connect();
  assert.equal(ui.get("account-member").hidden,false);
  assert.equal(ui.get("account-button").textContent,"Player One");
  const signed=ui.calls.find(call=>call.url==="wallet:signMessage");
  assert.equal(signed.input.message,"Blockword sign-in");
  assert.equal(signed.input.nonce,"nonce");
  assert.match(ui.get("account-status").textContent,/separate game account/);
  assert.equal(ui.calls.some(call=>["/api/start","/api/guess","/api/recover"].includes(call.url)),false);
});

test("wrong network stops before any wallet message is signed",async()=>{
  const ui=await page({chainId:2});await ui.open();await ui.connect();
  assert.match(ui.get("account-status").textContent,/Switch your wallet to Aptos devnet/);
  assert.equal(ui.calls.some(call=>call.url==="wallet:signMessage"),false);
  assert.equal(ui.calls.some(call=>call.url==="/api/auth/verify"),false);
});

test("unsupported key types are explained before starting a challenge",async()=>{
  const ui=await page({key:"0x"+"11".repeat(33)});await ui.open();await ui.connect();
  assert.match(ui.get("account-status").textContent,/Ed25519/);
  assert.equal(ui.calls.some(call=>call.url==="/api/auth/challenge"),false);
});

test("a rejected message creates no player session",async()=>{
  const ui=await page({rejected:true});await ui.open();await ui.connect();
  assert.match(ui.get("account-status").textContent,/Sign-in cancelled/);
  assert.equal(ui.calls.some(call=>call.url==="/api/auth/verify"),false);
  assert.equal(ui.get("account-member").hidden,true);
});

test("the profile form saves the player's chosen name",async()=>{
  const ui=await page();await ui.open();await ui.connect();
  ui.get("profile-name").value="My player";
  ui.get("profile-form").listeners.submit({preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  const saved=ui.calls.find(call=>call.url==="/api/account/me"&&call.request.method==="PATCH");
  assert.equal(JSON.parse(saved.request.body).display_name,"My player");
  assert.equal(ui.get("account-button").textContent,"My player");
});

test("signing out all sessions returns to the guest panel",async()=>{
  const ui=await page();await ui.open();await ui.connect();
  await ui.get("signout-all-button").listeners.click();
  assert.equal(ui.get("account-member").hidden,true);
  assert.equal(ui.get("account-button").textContent,"Player account");
  assert.ok(ui.calls.some(call=>call.url==="/api/auth/logout-all"&&call.request.method==="POST"));
});

test("an unavailable extension produces a useful local message",async()=>{
  const ui=await page({noWallet:true});await ui.open();
  assert.match(ui.get("wallet-choices").children[0].textContent,/No compatible Aptos wallet/);
});

test("an expired player session offers wallet sign-in again",async()=>{
  const options={};const ui=await page(options);await ui.open();await ui.connect();
  options.expired=true;await ui.open();
  assert.equal(ui.get("account-member").hidden,true);
  assert.equal(ui.get("account-button").textContent,"Player account");
  assert.match(ui.get("account-status").textContent,/Sign in again/);
  assert.equal(ui.get("wallet-choices").children[0].textContent,"Sign in with Test wallet");
});
