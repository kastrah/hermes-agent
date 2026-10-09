'use strict';
const form = document.querySelector('#login');
const status = document.querySelector('#status');
const password = document.querySelector('#password');
let csrf = '';
const token = location.hash.slice(1);
history.replaceState(null, '', '/');

async function post(path, body) {
  const response = await fetch(path, {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error('The link expired, the task ended, or access was refused. Ask Zuri for a new link.');
  return response.json();
}
function busy(value) {
  for (const button of form.querySelectorAll('button')) button.disabled = value;
}
function finish(message) {
  password.value = '';
  document.querySelector('#identifier').value = '';
  csrf = '';
  form.hidden = true;
  status.textContent = message;
}
document.querySelector('#show').addEventListener('change', event => {
  password.type = event.target.checked ? 'text' : 'password';
});
form.addEventListener('submit', async event => {
  event.preventDefault();
  busy(true);
  status.textContent = 'Sending securely…';
  const answer = { identifier: document.querySelector('#identifier').value, password: password.value };
  password.value = '';
  try {
    await post('/save', answer);
    finish('Secret received. Zuri will save it and continue only if the task is still active. Login autofill also requires the same site.');
  } catch (error) {
    finish(error.message);
  } finally {
    answer.identifier = answer.password = '';
    busy(false);
  }
});
document.querySelector('#cancel').addEventListener('click', async () => {
  busy(true);
  try { await post('/cancel', {}); finish('Cancelled. No login was saved.'); }
  catch (error) { finish(error.message); }
  finally { busy(false); }
});
if (!token) {
  status.textContent = 'Open the secure link from your Zuri conversation.';
} else {
  post('/claim', { token }).then(answer => {
    csrf = answer.csrf;
    const isLogin = answer.kind === 'login';
    const kind = answer.kind === 'api_key' ? 'API key' : 'token';
    document.querySelector('#heading').textContent = isLogin ? 'Save login securely' : `Save ${kind} securely`;
    document.querySelector('#site-label').textContent = isLogin ? 'Only use this login on' : 'Service';
    document.querySelector('#origin').textContent = isLogin ? answer.origin : answer.label;
    document.querySelector('#secret-label').textContent = isLogin ? 'Password' : kind === 'API key' ? 'API key' : 'Token';
    document.querySelector('#identifier-group').hidden = !isLogin;
    document.querySelector('#identifier').required = isLogin;
    password.autocomplete = isLogin ? 'current-password' : 'off';
    status.textContent = 'Private connection verified.';
    form.hidden = false;
  }).catch(error => { status.textContent = error.message; });
}
