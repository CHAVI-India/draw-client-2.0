import os

from django.test import TestCase


class RoiCacheFilenameTests(TestCase):
    """
    Mask-cache filenames are derived from ROI names that attackers can control
    (request JSON / RT Structure contents). They must always resolve inside the
    cache directory (CWE-22).
    """

    def test_traversal_name_produces_safe_filename(self):
        from dicom_handler.dicom_viewer_views import _roi_cache_filename

        name = _roi_cache_filename('../../../tmp/evil', '.pkl')
        self.assertNotIn('/', name)
        self.assertNotIn('\\', name)
        self.assertNotIn('..', name)
        self.assertTrue(name.endswith('.pkl'))
        self.assertEqual(name, os.path.basename(name))

    def test_failed_marker_extension(self):
        from dicom_handler.dicom_viewer_views import _roi_cache_filename

        name = _roi_cache_filename('../../x', '.failed')
        self.assertTrue(name.endswith('.failed'))
        self.assertEqual(name, os.path.basename(name))

    def test_deterministic_and_unique(self):
        from dicom_handler.dicom_viewer_views import _roi_cache_filename

        self.assertEqual(
            _roi_cache_filename('PTV', '.pkl'),
            _roi_cache_filename('PTV', '.pkl'),
        )
        self.assertNotEqual(
            _roi_cache_filename('PTV', '.pkl'),
            _roi_cache_filename('GTV', '.pkl'),
        )


class TaskIdFilenameTests(TestCase):
    """
    export.task_id is taken from the remote server response and interpolated
    into a download filename - it must be sanitized (CWE-22).
    """

    def test_task_id_traversal_sanitized(self):
        from dicom_handler.import_services.task1_poll_and_retrieve_rtstruct import (
            _sanitize_filename_component,
        )

        result = _sanitize_filename_component('../../etc/cron.d/x')
        self.assertNotIn('/', result)
        self.assertNotIn('..', result)

    def test_absolute_task_id_sanitized(self):
        from dicom_handler.import_services.task1_poll_and_retrieve_rtstruct import (
            _sanitize_filename_component,
        )

        result = _sanitize_filename_component('/etc/passwd')
        self.assertNotIn('/', result)

    def test_normal_task_id_unchanged(self):
        from dicom_handler.import_services.task1_poll_and_retrieve_rtstruct import (
            _sanitize_filename_component,
        )

        self.assertEqual(
            _sanitize_filename_component('a1b2c3-task_1234'),
            'a1b2c3-task_1234',
        )

    def test_empty_task_id_fallback(self):
        from dicom_handler.import_services.task1_poll_and_retrieve_rtstruct import (
            _sanitize_filename_component,
        )

        self.assertEqual(_sanitize_filename_component(''), 'unknown')
        self.assertEqual(_sanitize_filename_component('../../..'), 'unknown')


class CsrfTokenResolutionTests(TestCase):
    """
    Regression tests for the CSRF token resolution bug where AJAX/fetch POSTs
    failed with 403 (surfacing in the browser as a JSON.parse error, because the
    403 body is HTML).

    The front-end must never parse document.cookie with a hard-coded name (the
    server uses a custom CSRF_COOKIE_NAME) and must resolve the token from the
    server-rendered hidden input, then the server-rendered csrf_token variable
    (exposed via <meta name="csrf-token"> in base.html). static/js/csrf.js is the
    single shared helper; these tests mirror its resolution order.
    """

    AJAX_ENDPOINT = "/dicom/api/series-export-details/"  # login_required + CSRF-enforced JSON

    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_superuser(
            "csrf_tester", "csrf_tester@example.com", "s3cret-pass"
        )
        self.client = self._csrf_client()
        self.assertTrue(self.client.login(username="csrf_tester", password="s3cret-pass"))

    def _csrf_client(self):
        # Enforce CSRF exactly like the real middleware does.
        from django.test import Client

        return Client(enforce_csrf_checks=True)

    def _js_resolved_token(self, html):
        """Mirror of static/js/csrf.js: hidden input first, then the meta tag."""
        import re

        m = re.search(
            r'<input type="hidden" name="csrfmiddlewaretoken" value="([^"]*)"', html
        )
        if m and m.group(1):
            return m.group(1)
        m = re.search(r'<meta name="csrf-token" content="([^"]*)"', html)
        return (m.group(1) if m else "").strip()

    def _post_ajax(self, client, token):
        import json

        return client.post(
            self.AJAX_ENDPOINT,
            data=json.dumps({"series_uids": []}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )

    def test_formless_page_resolves_non_empty_token_via_meta(self):
        # series-status has no form on the page -> the hidden input is absent and
        # the JS helper must fall back to the meta tag ({{ csrf_token }} variable).
        resp = self.client.get("/dicom/series-status/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        token = self._js_resolved_token(html)
        self.assertTrue(
            token,
            "JS helper could not resolve a CSRF token on the rendered page",
        )

    def test_form_page_resolves_token_from_hidden_input(self):
        # template_list renders a {% csrf_token %} form -> the JS helper reads the
        # hidden input, which must be a real (non-empty) token.
        resp = self.client.get("/dicom/templates/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        token = self._js_resolved_token(html)
        self.assertTrue(token, "hidden-input token is empty on the rendered page")

    def test_ajax_post_with_resolved_token_passes_csrf(self):
        resp = self.client.get("/dicom/series-status/")
        token = self._js_resolved_token(resp.content.decode())
        resp = self._post_ajax(self.client, token)
        self.assertNotEqual(
            resp.status_code,
            403,
            "Resolved token was rejected (CSRF failure): the front-end would 403",
        )
        self.assertTrue(
            resp.content.lstrip()[:1] == b"{",
            "Expected a JSON body, got non-JSON (a 403 HTML page would break JSON.parse)",
        )

    def test_ajax_post_with_empty_token_403s_with_html(self):
        # Proves the guard is real: an empty/missing token is rejected with an
        # HTML 403 (the cryptic JSON.parse failure this fix removes).
        resp = self._post_ajax(self.client, "")
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(b"{", resp.content[:1])

    def test_base_template_loads_shared_csrf_helper(self):
        resp = self.client.get("/dicom/series-status/")
        html = resp.content.decode()
        self.assertIn("js/csrf.js", html, "base.html must load the shared helper")
        # The static file must exist and define window.CSRF.getToken.
        from django.contrib.staticfiles import finders

        path = finders.find("js/csrf.js")
        self.assertTrue(path, "static/js/csrf.js was not found")
        with open(path, "r", encoding="utf-8") as fh:
            self.assertIn("window.CSRF", fh.read())
        self.assertIn("getToken", open(path, encoding="utf-8").read())
