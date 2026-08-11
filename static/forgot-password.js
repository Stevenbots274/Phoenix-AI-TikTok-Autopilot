const form = document.querySelector('#forgot-form');
const error = document.querySelector('#form-error');
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const label = document.querySelector('#submit-label');
  const spinner = document.querySelector('#submit-spinner');
  label.classList.add('hidden'); spinner.classList.remove('hidden'); error.classList.add('hidden');
  try {
    const email = new FormData(form).get('email');
    const response = await fetch('/api/auth/forgot-password', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ email }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to send reset link');
    error.textContent = 'If that account exists, a reset link is on its way.';
    error.classList.remove('hidden');
  } catch (exception) { error.textContent = exception.message; error.classList.remove('hidden'); }
  finally { label.classList.remove('hidden'); spinner.classList.add('hidden'); }
});
