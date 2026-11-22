/**
 * Shared CSRF token resolver for AJAX/fetch POST requests.
 *
 * Resolution order (cookie-name independent -- the server's
 * CSRF_COOKIE_NAME is intentionally custom, so we must NOT parse
 * document.cookie by a hard-coded name):
 *
 *   1. The server-rendered hidden input[name=csrfmiddlewaretoken]
 *      (rendered by any {% csrf_token %} form on the page).
 *   2. The server-rendered {{ csrf_token }} variable, exposed by
 *      <meta name="csrf-token" content="{{ csrf_token }}"> in base.html.
 *
 * If neither source has a value, an Error is thrown instead of sending
 * an empty header: an empty X-CSRFToken produces a 403 whose HTML body
 * would otherwise surface as a cryptic JSON.parse error in the caller.
 *
 * Usage (any page that extends base.html):
 *   headers: { 'X-CSRFToken': window.CSRF.getToken() }
 */
(function () {
    'use strict';

    function readMetaToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (!meta) {
            return '';
        }
        return (meta.getAttribute('content') || '').trim();
    }

    function readHiddenInputToken() {
        var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (!input || !input.value) {
            return '';
        }
        return input.value.trim();
    }

    window.CSRF = {
        /**
         * Resolve the CSRF token for the current page.
         *
         * @param {boolean} [allowEmpty=false] - when true, return '' instead
         *        of throwing if no token can be resolved (use only for
         *        non-essential requests); POSTs to CSRF-enforced endpoints
         *        must leave this false.
         * @returns {string} the CSRF token
         * @throws {Error} when no token can be resolved and !allowEmpty
         */
        getToken: function (allowEmpty) {
            var token = readHiddenInputToken() || readMetaToken();
            if (token) {
                return token;
            }
            if (allowEmpty) {
                return '';
            }
            throw new Error(
                'CSRF token could not be resolved: no ' +
                'input[name="csrfmiddlewaretoken"] and no non-empty ' +
                'meta[name="csrf-token"] on this page. Ensure the page ' +
                'renders a {% csrf_token %} form or the ' +
                'django.template.context_processors.csrf context processor ' +
                'is enabled, then reload the page.'
            );
        },
    };
})();
