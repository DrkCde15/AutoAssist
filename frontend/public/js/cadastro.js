(function() {
  var submitBtn = document.getElementById('submitBtn');
  var errorDiv = document.getElementById('error');
  var turnstileToken = null;
  var turnstileWidgetId = null;

  function waitForTurnstile(cb) {
    if (typeof turnstile !== 'undefined') return cb();
    var t = setInterval(function() {
      if (typeof turnstile !== 'undefined') { clearInterval(t); cb(); }
    }, 50);
  }

  fetch('/api/config/public').then(function(r){return r.json()}).then(function(d){
    var key = d.turnstile_site_key;
    if (key) {
      waitForTurnstile(function() {
        turnstileWidgetId = turnstile.render('#turnstileBox', {
          sitekey: key,
          action: 'signup',
          theme: 'dark',
          callback: function(token) { turnstileToken = token; submitBtn.disabled = false; },
          'expired-callback': function() { turnstileToken = null; submitBtn.disabled = true; },
          'error-callback': function() { turnstileToken = null; submitBtn.disabled = true; }
        });
      });
    } else {
      submitBtn.disabled = false;
    }
  }).catch(function(){
    submitBtn.disabled = false;
  });

  // Programa de indicação: captura ?ref= e exibe banner
  var referralCode = null;
  try {
    referralCode = new URLSearchParams(window.location.search).get("ref");
    if (referralCode) {
      referralCode = referralCode.trim().substring(0, 20) || null;
      var banner = document.getElementById("referral-banner");
      if (banner) banner.classList.remove("hidden");
    }
  } catch (e) { referralCode = null; }

  document.getElementById('signupForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    errorDiv.classList.add('hidden');

    var nome = document.getElementById('name').value.trim();
    var email = document.getElementById('email').value.trim();
    var confirmEmail = document.getElementById('confirm-email').value.trim();
    var password = document.getElementById('password').value;
    var confirmEmailInput = document.getElementById('confirm-email');
    var password2 = document.getElementById('password2').value;

    if (confirmEmailInput && email !== confirmEmail) {
      errorDiv.textContent = 'Os e-mails não coincidem.';
      errorDiv.classList.remove('hidden');
      return;
    }

    if (password !== password2) {
      errorDiv.textContent = 'As senhas não coincidem.';
      errorDiv.classList.remove('hidden');
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Criando conta...';

    var token = turnstileToken;

    try {
      await auth.register({
        nome: nome,
        email: email,
        confirm_email: confirmEmail,
        password: password,
        confirm_password: password2,
        turnstile_token: token,
        referred_by: referralCode
      });
      var params = new URLSearchParams(window.location.search);
      var plan = params.get("plan");
      var redirectUrl = '/login?conta criada';
      if (plan === "premium") redirectUrl = '/login?redirect=' + encodeURIComponent('/planos');
      window.location.href = redirectUrl;
    } catch(err) {
      errorDiv.textContent = err.message || 'Erro ao criar conta. Tente novamente.';
      errorDiv.classList.remove('hidden');
      submitBtn.disabled = false;
      submitBtn.textContent = 'Criar conta';
      if (typeof turnstile !== 'undefined' && turnstileWidgetId !== null) {
        turnstileToken = null;
        turnstile.reset(turnstileWidgetId);
      }
    }
  });
})();
