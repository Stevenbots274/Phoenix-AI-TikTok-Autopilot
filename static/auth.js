const mode = window.location.pathname.startsWith('/signup') ? 'signup' : 'login';
const $ = (selector) => document.querySelector(selector);

function setMode() {
  const signup = mode === 'signup';
  document.title = signup ? 'Create account · Phoenix Autopilot' : 'Sign in · Phoenix Autopilot';
  $('#form-eyebrow').textContent = signup ? 'Start your practice' : 'Welcome back';
  $('#form-title').textContent = signup ? 'Create your Phoenix account' : 'Sign in to Phoenix';
  $('#form-copy').textContent = signup ? 'A better system starts with one good idea.' : 'Your next good idea is waiting.';
  $('#name-field').classList.toggle('hidden', !signup);
  $('#name-field input').required = signup;
  $('#login-tab').classList.toggle('active', !signup);
  $('#signup-tab').classList.toggle('active', signup);
  $('#submit-label').textContent = signup ? 'Create account' : 'Sign in';
  $('#top-switch').textContent = signup ? 'Sign in' : 'Create account';
  $('#top-switch').href = signup ? '/login' : '/signup';
  $('input[name="password"]').autocomplete = signup ? 'new-password' : 'current-password';
}

async function submit(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const error = $('#form-error'); const label = $('#submit-label'); const spinner = $('#submit-spinner');
  error.classList.add('hidden'); label.classList.add('hidden'); spinner.classList.remove('hidden');
  try {
    const response = await fetch(`/api/auth/${mode === 'signup' ? 'signup' : 'login'}`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(Object.fromEntries(form.entries())) });
    const data = await response.json();
    if (!response.ok) {
      if (data.verification_required) $('#verification-help').classList.remove('hidden');
      throw new Error(data.error || 'Unable to continue');
    }
    if (data.verification_required) {
      error.textContent = 'Check your inbox for a verification link before signing in.';
      error.classList.remove('hidden');
      $('#verification-help').classList.remove('hidden');
      return;
    }
    window.location.href = '/app';
  } catch (exception) { error.textContent = exception.message; error.classList.remove('hidden'); } finally { label.classList.remove('hidden'); spinner.classList.add('hidden'); }
}

setMode();
if (new URLSearchParams(window.location.search).get('verified') === '1') {
  $('#form-error').textContent = 'Email verified. You can sign in now.';
  $('#form-error').classList.remove('hidden');
}
if (new URLSearchParams(window.location.search).get('verified') === 'error') {
  $('#form-error').textContent = 'That verification link is invalid or expired.';
  $('#form-error').classList.remove('hidden');
}
$('#auth-form').addEventListener('submit', submit);
$('#resend-verification').addEventListener('click', async () => {
  const email = $('input[name="email"]').value.trim();
  try {
    const response = await fetch('/api/auth/resend-verification', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ email }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to resend verification email');
    $('#form-error').textContent = 'A new verification email is on its way.';
    $('#form-error').classList.remove('hidden');
  } catch (exception) { $('#form-error').textContent = exception.message; $('#form-error').classList.remove('hidden'); }
});
