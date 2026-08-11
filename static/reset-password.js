const form = document.querySelector('#reset-form');
const error = document.querySelector('#form-error');
const token = new URLSearchParams(window.location.search).get('token') || '';
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form).entries());
  if (!token) { error.textContent = 'This reset link is missing or invalid.'; error.classList.remove('hidden'); return; }
  if (data.password !== data.confirm_password) { error.textContent = 'The passwords do not match.'; error.classList.remove('hidden'); return; }
  const label = document.querySelector('#submit-label');
  const spinner = document.querySelector('#submit-spinner');
  label.classList.add('hidden'); spinner.classList.remove('hidden'); error.classList.add('hidden');
  try {
    const response = await fetch('/api/auth/reset-password', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ token, password:data.password }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Unable to reset password');
    error.textContent = 'Password updated. You can sign in now.';
    error.classList.remove('hidden');
    form.querySelector('button').disabled = true;
  } catch (exception) { error.textContent = exception.message; error.classList.remove('hidden'); }
  finally { label.classList.remove('hidden'); spinner.classList.add('hidden'); }
});
