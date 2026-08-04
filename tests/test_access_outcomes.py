from ai_websearch.access_outcomes import classify_access_outcome


def test_structural_captcha_markers_detected() -> None:
    for marker in (
        '<div class="g-recaptcha">Vérification humaine</div>',
        '<div class="recaptcha-checkbox">Bestätigung</div>',
        '<div class="cf-turnstile-widget">Verifica</div>',
        '<div class="h-captcha">Verifica che sei umano</div>',
        '<div class="challenge-container">Verification</div>',
        '<div class="cf-challenge-running">Security</div>',
        '<div class="brcaptcha">Human check</div>',
        '<div class="cf-browser-verification">Checking</div>',
    ):
        result = classify_access_outcome("Security", marker, "Some page text")
        assert result == "captcha", f"Expected captcha for {marker}"


def test_structural_cookie_consent_markers_detected() -> None:
    for marker in (
        '<div class="cc-window">Accept cookies</div>',
        '<div id="cookieconsent">Cookies</div>',
        '<div id="onetrust-banner-sdk">Cookie-Einstellungen</div>',
        '<div id="onetrust">Cookies</div>',
        '<div id="osano-cm">Cookies</div>',
        '<div id="usercentrics-root">Cookies</div>',
        '<div id="cookielawinfo">Cookies</div>',
        '<div class="privacy-notice">Privacy</div>',
        '<div class="privacy-banner">Cookies</div>',
        '<div class="gdpr-banner">GDPR</div>',
        '<div class="tcfelement">Consent</div>',
        '<div class="cookie-policy">Cookies</div>',
        '<div class="cf-cookie-alert">Cloudflare cookies</div>',
        '<div class="cookie-banner">Cookies</div>',
        '<div class="cookie-notice">Cookies</div>',
    ):
        result = classify_access_outcome("Cookies", marker, "Page content here")
        assert result == "cookie_consent", f"Expected cookie_consent for {marker}"


def test_structural_authentication_markers_detected() -> None:
    for marker in (
        '<div id="password-input">Password</div>',
        '<div id="username-field">User</div>',
        '<div id="email-field">Email</div>',
        '<div id="auth-container">Login</div>',
        '<div id="sign-in-btn">Sign in</div>',
        '<div id="signin-btn">Sign in</div>',
        '<div id="login-btn">Login</div>',
        '<div id="auth-form-container">Auth</div>',
        '<div id="credentials-form">Credentials</div>',
        '<form><input type="password"></form>',
    ):
        result = classify_access_outcome("Login", marker, "Sign in to access")
        assert result == "authentication", f"Expected authentication for {marker}"


def test_structural_subscription_markers_detected() -> None:
    for marker in (
        '<div class="paywall-overlay">Subscribe</div>',
        '<div class="subscription-modal">Premium</div>',
        '<div class="subscriber-only">Members</div>',
        '<div class="premium-content">Premium</div>',
        '<div class="gated-content">Gated</div>',
        '<div class="register-wall">Register</div>',
        '<div class="paywall-gate">Paywall</div>',
        '<div class="locked-content">Locked</div>',
        '<div class="members-only">Members</div>',
        '<div class="vip-content">VIP</div>',
    ):
        result = classify_access_outcome("Subscribe", marker, "Premium content")
        assert result == "subscription", f"Expected subscription for {marker}"


def test_structural_access_denied_markers_detected() -> None:
    for marker in (
        '<div class="error-page">Error</div>',
        '<div class="blocked-page">Blocked</div>',
        '<div class="waf-block">WAF</div>',
        '<div class="security-block">Security</div>',
        '<div class="access-restricted">Restricted</div>',
        '<div class="ip-blocked">IP blocked</div>',
        '<div class="rate-limited">Rate limited</div>',
    ):
        result = classify_access_outcome("Error", marker, "Error page text")
        assert result == "access_denied", f"Expected access_denied for {marker}"


def test_vendor_consent_iframe_detected() -> None:
    for html in (
        '<iframe src="https://consent.cookiebot.com/sdk/js"></iframe>',
        '<script src="https://cdn.cookielaw.org/script.js"></script>',
        '<script src="https://cdn.usercentrics.eu/uc.js"></script>',
        '<script src="https://cmp.osano.com/consent.js"></script>',
        '<script src="https://app.didomi.io/consent.js"></script>',
        '<script src="https://cdn.consentmanager.net/consent.js"></script>',
        '<script src="https://app.privacy-center.org/consent.js"></script>',
    ):
        result = classify_access_outcome("Cookies", html, "Page content here")
        assert result == "cookie_consent", f"Expected cookie_consent for {html}"


def test_vendor_captcha_iframe_detected() -> None:
    for html in (
        '<div><iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe></div>',
        '<div><iframe src="https://recaptcha.net/recaptcha/anchor"></iframe></div>',
        '<div><iframe src="https://challenges.cloudflare.com/captcha-v2"></iframe></div>',
        '<div><iframe src="https://js.hcaptcha.com/1/api.js"></iframe></div>',
        '<div><iframe src="https://cn.brcdn.com/captcha"></iframe></div>',
        '<div><iframe src="https://cn.brecaptcha.net/captcha"></iframe></div>',
    ):
        result = classify_access_outcome("Verify", html, "Security check required")
        assert result == "captcha", f"Expected captcha for {html}"


def test_vendor_subscription_link_detected() -> None:
    html = '<link href="/paywall/gate" rel="stylesheet">'
    result = classify_access_outcome("Premium", html, "Content behind paywall")
    assert result == "subscription"


def test_structural_takes_precedence_over_text_patterns() -> None:
    html = '<div class="cf-turnstile">This is a normal article</div>'
    markdown = (
        "The study documents the bridge design, measurement method, "
        "observed vibration, load capacity, and engineering limitations."
    )
    result = classify_access_outcome("Bridge report", html, markdown)
    assert result == "captcha"


def test_substantive_article_without_markers_is_success() -> None:
    markdown = (
        "The field study documents the bridge design, measurement method, "
        "observed vibration, load capacity, and engineering limitations."
    )
    result = classify_access_outcome("Bridge report", None, markdown)
    assert result == "success"


def test_non_english_consent_with_structural_marker_detected() -> None:
    html = '<div id="onetrust-banner-sdk">Alle akzeptieren. Verwalten Sie Ihre Einstellungen.</div>'
    markdown = "Alle akzeptieren. Verwalten Sie Ihre Datenschutz-Einstellungen."
    result = classify_access_outcome("Cookie-Einstellungen", html, markdown)
    assert result == "cookie_consent"


def test_non_english_auth_with_structural_marker_detected() -> None:
    html = '<form id="auth-container"><input type="password"></form>'
    markdown = "Inicia sesion para continuar a este recurso."
    result = classify_access_outcome("Iniciar sesion", html, markdown)
    assert result == "authentication"


def test_non_english_consent_without_marker_falls_through_to_quality() -> None:
    markdown = (
        "Alle akzeptieren. Verwalten Sie Ihre Datenschutz- und Cookie-Einstellungen. "
        "Partner konnen diese Funktion nutzen. Tracking-Technologien werden eingesetzt."
    )
    result = classify_access_outcome("Cookie-Einstellungen", None, markdown)
    assert result == "success"


def test_empty_html_returns_success_for_substantive_content() -> None:
    markdown = (
        "The monitoring program measured water temperature, salinity, and "
        "dissolved oxygen at twelve public stations."
    )
    result = classify_access_outcome("Monitoring report", "", markdown)
    assert result == "success"
