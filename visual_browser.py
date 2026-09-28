"""Isolated, bounded Chromium viewport capture and computed style extraction."""
import ipaddress
import json
import socket
from urllib.parse import urlsplit

from web_ingest import target

STYLE_SCRIPT = r"""() => {
  const short = value => String(value || '').slice(0, 180);
  const css = element => element ? getComputedStyle(element) : null;
  const sample = selector => {
    const s = css(document.querySelector(selector));
    return s ? {fontFamily: short(s.fontFamily), fontSize: short(s.fontSize),
      fontWeight: short(s.fontWeight), lineHeight: short(s.lineHeight)} : null;
  };
  const body = css(document.body), root = css(document.documentElement);
  const button = css(document.querySelector('button, [role=button]'));
  const anchor = css(document.querySelector('a[href]'));
  const colors = {
    background: short(body?.backgroundColor || root?.backgroundColor),
    foreground: short(body?.color),
    accent: short(anchor?.color),
    button: short(button?.backgroundColor),
    buttonText: short(button?.color)
  };
  const counts = new Map();
  for (const element of Array.from(document.querySelectorAll('main *, header *, body > *')).slice(0, 400)) {
    const s = css(element);
    for (const value of [s?.backgroundColor, s?.color]) {
      if (value && value !== 'rgba(0, 0, 0, 0)' && value !== 'transparent') {
        counts.set(value, (counts.get(value) || 0) + 1);
      }
    }
  }
  const palette = [...counts].sort((a,b) => b[1] - a[1]).slice(0, 8).map(([color]) => short(color));
  const meta = name => short(document.querySelector('meta[name="' + name + '"]')?.content);
  const favicon = document.querySelector('link[rel~="icon"]')?.href || '';
  return {
    mode: 'computed', colors, palette,
    typography: {p: sample('p') || sample('body'), headings: {h1: sample('h1'), h2: sample('h2')},
      button: sample('button')},
    components: {button: button ? {borderRadius: short(button.borderRadius),
      padding: short(button.padding), boxShadow: short(button.boxShadow)} : null},
    metadata: {title: short(document.title), description: meta('description'),
      favicon: short(favicon)},
    viewport: {width: window.innerWidth, height: window.innerHeight}
  };
}"""


def public_host(url):
    """Reject local destinations and redirects before Chromium contacts them."""
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
        return False
    try:
        target(url)
        addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)
    except (OSError, ValueError):
        return False


def render(url):
    if not public_host(url):
        raise ValueError('Only public HTTPS destinations can be captured')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, chromium_sandbox=True)
        try:
            context = browser.new_context(viewport={'width': 1280, 'height': 900},
                device_scale_factor=1, service_workers='block', accept_downloads=False,
                ignore_https_errors=False)
            try:
                page = context.new_page()
                page.set_default_timeout(12_000)
                requests = [0]
                def guard(route):
                    requests[0] += 1
                    request = route.request
                    if (requests[0] > 150 or not public_host(request.url) or
                            request.resource_type in ('media', 'websocket', 'eventsource')):
                        route.abort()
                    else:
                        route.continue_()
                context.route('**/*', guard)
                context.on('page', lambda popup: popup.close() if popup != page else None)
                page.goto(url, wait_until='domcontentloaded', timeout=30_000)
                page.wait_for_timeout(1000)
                image = page.screenshot(type='jpeg', quality=72, full_page=False,
                                        animations='disabled', timeout=12_000)
                guide = page.evaluate(STYLE_SCRIPT)
                if not isinstance(guide, dict) or len(json.dumps(guide).encode()) > 100_000:
                    raise ValueError('Styleguide exceeded its storage limit')
                return image, guide
            finally:
                context.close()
        finally:
            browser.close()
