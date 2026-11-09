"""Swagger UI (/docs) with a smoother Keycloak sign-in.

Stock Swagger UI makes people open an "Available authorizations" dialog and
click Authorize a second time, and its button never changes after login.
This page adds a small script that:
  * sends a click on "Authorize" straight to the Keycloak login (the dialog
    is skipped when a client_id is configured, otherwise it is shown as usual);
  * relabels the button "Authorized" and turns it green (outline only; red while signed
    out) once a token is held (the dialog, with its Logout button, is still reachable by clicking it);
  * signs the page out when the token expires (Swagger never refreshes it).

The token lives only in the page: a reload signs you out, and nothing is stored
in the browser.

The script only touches Swagger's DOM, so if a future Swagger version changes
that markup it simply stops doing anything and the stock dialog works as before.
"""

from fastapi.openapi.docs import (
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from starlette.requests import Request
from starlette.responses import HTMLResponse

SCRIPT = """
(function () {
  var busy = false;
  var wantLogin = false;   // true only after the user pressed Authorize while signed out
  var style = document.createElement('style');
  style.textContent =
    'body.sw-autoauth .dialog-ux { visibility: hidden !important; }' +
    /* signed out: red outline, red text and padlock */
    '.swagger-ui .auth-wrapper .btn.authorize.unlocked { border-color: #f93e3e; color: #f93e3e; }' +
    '.swagger-ui .auth-wrapper .btn.authorize.unlocked svg, .swagger-ui .auth-wrapper .btn.authorize.unlocked svg path { fill: #f93e3e !important; }' +
    /* signed in: green outline, green text and padlock, no fill */
    '.swagger-ui .auth-wrapper .btn.authorize.locked { background-color: transparent; border-color: #49cc90; color: #49cc90; }' +
    '.swagger-ui .auth-wrapper .btn.authorize.locked svg, .swagger-ui .auth-wrapper .btn.authorize.locked svg path { fill: #49cc90 !important; }' +
    /* the small padlock on every endpoint row follows the same colours */
    '.swagger-ui .authorization__btn svg.unlocked { color: #f93e3e; fill: #f93e3e; }' +
    '.swagger-ui .authorization__btn svg.locked { color: #49cc90; fill: #49cc90; }';
  document.head.appendChild(style);

  function relabel() {
    document.querySelectorAll('.auth-wrapper button.authorize').forEach(function (b) {
      var span = b.querySelector('span');
      if (!span) return;
      var want = b.classList.contains('locked') ? 'Authorized' : 'Authorize';
      if (span.textContent !== want) span.textContent = want;
    });
  }

  // Swagger never refreshes the token: once it expires, sign the page out so the
  // button does not claim "Authorized" while every request answers 401.
  function dropExpired() {
    try {
      var all = ui.authSelectors.authorized().toJS(), names = [];
      Object.keys(all).forEach(function (n) {
        var t = all[n] && all[n].token && all[n].token.access_token;
        if (!t) return;
        var p = JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
        if (p.exp && p.exp * 1000 <= Date.now()) names.push(n);
      });
      if (names.length) ui.authActions.logout(names);
    } catch (e) { /* not a JWT or no auth state yet: leave it alone */ }
  }

  // Remember what the user just asked for, so that the dialog re-appearing after
  // "Logout" (it then shows Authorize again) is NOT mistaken for a login request.
  document.addEventListener('click', function (ev) {
    var t = ev.target.closest ? ev.target : ev.target.parentElement;
    var top = t && t.closest('.auth-wrapper > button.authorize');
    if (top) wantLogin = !top.classList.contains('locked');
    var out = t && t.closest('.dialog-ux .auth-btn-wrapper button');
    if (out && out.textContent.trim() === 'Logout') {
      wantLogin = false;
      setTimeout(function () {                // signed out: just close the dialog
        var done = document.querySelector('.dialog-ux .btn-done');
        if (done) done.click();
      }, 50);
    }
  }, true);

  function skipDialog() {
    if (busy || !wantLogin) return;
    var dlg = document.querySelector('.dialog-ux');
    if (!dlg) return;
    var go = null;
    dlg.querySelectorAll('.auth-btn-wrapper button').forEach(function (b) {
      if (b.textContent.trim() === 'Authorize') go = b;
    });
    var cid = dlg.querySelector('input[id^="client_id"]');
    if (!go || !cid || !cid.value) return;   // logged in, or no client_id: keep the dialog
    busy = true;
    wantLogin = false;
    document.body.classList.add('sw-autoauth');
    go.click();                               // opens the Keycloak login window
    setTimeout(function () {
      var done = dlg.querySelector('.btn-done');
      if (done) done.click();                 // close the (hidden) dialog
      document.body.classList.remove('sw-autoauth');
      busy = false;
    }, 50);
  }

  new MutationObserver(function () { relabel(); skipDialog(); })
    .observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  dropExpired();
  relabel();
  setInterval(dropExpired, 5000);
  window.addEventListener('focus', dropExpired);
})();
"""


def install_docs(app, init_oauth=None):
    """Serve /docs and its OAuth redirect page without the global auth dependency.

    The FastAPI app must be created with docs_url=None and
    swagger_ui_oauth2_redirect_url=None. Routes added with add_route() bypass
    the app-wide `dependencies=[...]`, so the docs stay public.
    """

    async def docs(request: Request):
        root = request.scope.get("root_path", "").rstrip("/")
        html = get_swagger_ui_html(
            openapi_url=root + app.openapi_url,
            title=f"{app.title} - Swagger UI",
            oauth2_redirect_url=root + "/docs/oauth2-redirect",
            init_oauth=init_oauth,
        ).body.decode()
        return HTMLResponse(html.replace("</body>", f"<script>{SCRIPT}</script></body>"))

    async def oauth2_redirect(request: Request):
        return get_swagger_ui_oauth2_redirect_html()

    app.add_route("/docs", docs, include_in_schema=False)
    app.add_route("/docs/oauth2-redirect", oauth2_redirect, include_in_schema=False)
