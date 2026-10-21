import {getWallets} from "/static/vendor/wallet-standard/wallets.js";

const element = id => document.getElementById(id);
const registry = getWallets();
let player = null, working = false, activeWallet = null;

function notice(message,error=false) {
  element("account-status").textContent=message;
  element("account-status").classList.toggle("error",error);
}

async function request(url,method="GET",body) {
  let response;
  try {
    response=await fetch(url,{method,credentials:"same-origin",headers:body?{"Content-Type":"application/json"}:{},
                             body:body?JSON.stringify(body):undefined});
  } catch {throw new Error("The account service could not be reached. Check your connection and try again.");}
  const result=await response.json().catch(()=>({detail:"The account service returned an unreadable response."}));
  if(!response.ok) {
    if(response.status===401 && url.startsWith("/api/account/")) {player=null;render();showWallets();}
    const error=new Error(typeof result.detail==="string"?result.detail:"Please check the account request.");error.status=response.status;throw error;
  }
  return result;
}

function render() {
  element("account-button").textContent=player?player.display_name:"Player account";
  element("account-guest").hidden=Boolean(player);
  element("account-member").hidden=!player;
  if(player) {
    element("profile-name").value=player.display_name;
    element("account-wallet").textContent=player.wallet_address;
    element("account-links").textContent=`${player.linked_demo_accounts} demo account${player.linked_demo_accounts===1?"":"s"} linked`;
  }
}

async function action(work) {
  if(working)return;
  working=true;
  element("account-dialog").querySelectorAll("button,input").forEach(control=>{control.disabled=true;});
  try {await work();}
  catch(error) {notice(error.message,true);}
  finally {working=false;element("account-dialog").querySelectorAll("button,input").forEach(control=>{control.disabled=false;});render();}
}

function wallets() {
  return registry.get().filter(wallet=>["aptos:connect","aptos:signMessage","aptos:network"].every(name=>wallet.features[name]));
}

function showWallets() {
  const list=element("wallet-choices");list.replaceChildren();
  for(const wallet of wallets()) {
    const button=document.createElement("button");button.className="wallet-choice";button.textContent=`Sign in with ${wallet.name}`;
    button.addEventListener("click",()=>action(()=>signIn(wallet)));list.append(button);
  }
  if(!list.children.length) {
    const message=document.createElement("p");message.className="tiny-note";
    message.textContent="No compatible Aptos wallet was found in this browser. Open Blockword in a browser with an Ed25519 wallet, such as Petra.";
    list.append(message);
  }
}

async function signIn(wallet) {
  notice("Approve the connection in your wallet. No transaction will be sent.");
  const connected=await wallet.features["aptos:connect"].connect();
  if(connected.status!=="Approved")throw new Error("Wallet connection cancelled.");
  const account=connected.args;
  if(!account?.publicKey || !account?.address)throw new Error("The wallet did not return a supported account. Try reconnecting with a standard Ed25519 account.");
  const publicKey=account.publicKey.toString();
  if(!/^0x[0-9a-f]{64}$/i.test(publicKey))throw new Error("This version supports standard Ed25519 wallet accounts. Keyless and multisig sign-in are not available yet.");
  const challenge=await request("/api/auth/challenge","POST",{wallet_address:account.address.toString()});
  const network=await wallet.features["aptos:network"].network();
  if(!network || network.chainId===undefined)throw new Error("The wallet did not report its network. Check its network settings and try again.");
  if(Number(network.chainId)!==challenge.chain_id)throw new Error("Switch your wallet to Aptos devnet, then sign in again.");
  notice("Read the Blockword sign-in message in your wallet, then approve it to continue.");
  const signed=await wallet.features["aptos:signMessage"].signMessage(challenge.sign_message);
  if(signed.status!=="Approved")throw new Error("Sign-in cancelled. No player session was created.");
  if(!signed.args?.signature || typeof signed.args.fullMessage!=="string")throw new Error("The wallet did not return a complete signed message. Try signing in again.");
  const result=await request("/api/auth/verify","POST",{
    challenge_id:challenge.challenge_id,public_key:publicKey,signature:signed.args.signature.toString(),full_message:signed.args.fullMessage,
  });
  activeWallet=wallet;player=result.player;render();
  await loadMemberData();
  notice("You're signed in. Your wallet key stays in your wallet; demo rounds still use a separate game account.");
}

async function loadMemberData() {
  const [sessions,rounds]=await Promise.all([request("/api/account/sessions"),request("/api/account/rounds?limit=20")]);
  const devices=element("account-sessions");devices.replaceChildren();
  for(const session of sessions.items) {
    const row=document.createElement("div");row.className="account-row";
    const label=document.createElement("span");label.textContent=`${session.current?"This session":"Another session"} · expires ${new Date(session.expires_at*1000).toLocaleString()}`;
    const button=document.createElement("button");button.className="text-button";button.textContent=session.current?"Sign out":"Revoke";
    button.addEventListener("click",()=>action(async()=>{
      await request(`/api/account/sessions/${session.id}`,"DELETE");
      if(session.current) {player=null;render();notice("This player session has ended.");}
      else {await loadMemberData();notice("That session has been revoked.");}
    }));row.append(label,button);devices.append(row);
  }
  const history=element("account-rounds");history.replaceChildren();
  for(const round of rounds.items) {
    const card=document.createElement("article");card.className="saved-term";
    const title=document.createElement("strong");title.textContent=round.answer.toUpperCase();
    const definition=document.createElement("p");definition.textContent=round.definition;
    const result=document.createElement("small");result.textContent=`Round ${round.round_id} · ${round.won?"Found":"Ended"} in ${round.board.length} guesses · saved ${new Date(round.recorded_at*1000).toLocaleDateString()}`;
    card.append(title,definition,result);history.append(card);
  }
  if(!rounds.items.length) {const empty=document.createElement("p");empty.className="tiny-note";empty.textContent="No saved rounds yet. Link this browser's demo history, then complete or recover a verified round.";history.append(empty);}
}

element("account-button").addEventListener("click",async()=>{
  element("account-dialog").showModal();showWallets();
  if(player)await action(async()=>{player=await request("/api/account/me");await loadMemberData();});
});
element("account-close").addEventListener("click",()=>element("account-dialog").close());
element("profile-form").addEventListener("submit",event=>{
  event.preventDefault();action(async()=>{player=await request("/api/account/me","PATCH",{display_name:element("profile-name").value});notice("Your player name is saved.");});
});
element("link-demo-button").addEventListener("click",()=>action(async()=>{
  player=await request("/api/account/link-demo","POST",{});await loadMemberData();notice("This demo history is linked to your player profile.");
}));
element("signout-all-button").addEventListener("click",()=>action(async()=>{
  await request("/api/auth/logout-all","POST",{});player=null;
  if(activeWallet?.features["aptos:disconnect"])await activeWallet.features["aptos:disconnect"].disconnect().catch(()=>{});
  activeWallet=null;render();notice("All of your player sessions have been signed out.");
}));
registry.on("register",()=>{if(!player)showWallets();});
request("/api/account/me").then(value=>{player=value;render();}).catch(error=>{if(error.status!==401)notice(error.message,true);render();});
render();
