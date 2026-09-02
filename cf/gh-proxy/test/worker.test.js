import { test } from 'node:test';
import assert from 'node:assert';
import worker from '../src/worker.js';

test('gh-proxy worker', async (t) => {
  await t.test('rejects request from non-whitelisted IP', async () => {
    const req = new Request('https://gh-proxy.test/https://github.com/test/repo', {
      headers: {
        'cf-connecting-ip': '1.2.3.4',
        'x-proxy-key': 'test-key'
      }
    });
    const env = { PROXY_KEY: 'test-key' };
    const res = await worker.fetch(req, env);
    assert.strictEqual(res.status, 404);
  });

  await t.test('accepts request from whitelisted IP', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      return new Response('ok', { status: 200 });
    };

    try {
      const req = new Request('https://gh-proxy.test/https://github.com/test/repo', {
        headers: {
          'cf-connecting-ip': '47.111.21.195',
          'x-proxy-key': 'test-key'
        }
      });
      const env = { PROXY_KEY: 'test-key' };
      const res = await worker.fetch(req, env);
      assert.strictEqual(res.status, 200);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('rejects request without PROXY_KEY', async () => {
    const req = new Request('https://gh-proxy.test/https://github.com/test/repo', {
      headers: { 'cf-connecting-ip': '47.111.21.195' }
    });
    const env = { PROXY_KEY: 'test-key' };
    const res = await worker.fetch(req, env);
    assert.strictEqual(res.status, 404);
  });

  await t.test('rejects request with wrong PROXY_KEY', async () => {
    const req = new Request('https://gh-proxy.test/https://github.com/test/repo', {
      headers: {
        'cf-connecting-ip': '47.111.21.195',
        'x-proxy-key': 'wrong-key'
      }
    });
    const env = { PROXY_KEY: 'test-key' };
    const res = await worker.fetch(req, env);
    assert.strictEqual(res.status, 404);
  });

  await t.test('rejects non-https target', async () => {
    const req = new Request('https://gh-proxy.test/http://github.com/test/repo', {
      headers: {
        'cf-connecting-ip': '47.111.21.195',
        'x-proxy-key': 'test-key'
      }
    });
    const env = { PROXY_KEY: 'test-key' };
    const res = await worker.fetch(req, env);
    assert.strictEqual(res.status, 400);
    assert.strictEqual(await res.text(), 'usage: /https://github.com/...');
  });

  await t.test('rejects invalid target URL', async () => {
    // Use a malformed URL that will fail URL constructor
    const req = new Request('https://gh-proxy.test/https://', {
      headers: {
        'cf-connecting-ip': '47.111.21.195',
        'x-proxy-key': 'test-key'
      }
    });
    const env = { PROXY_KEY: 'test-key' };
    const res = await worker.fetch(req, env);
    assert.strictEqual(res.status, 400);
    assert.strictEqual(await res.text(), 'invalid target url');
  });

  await t.test('rejects non-whitelisted host', async () => {
    const req = new Request('https://gh-proxy.test/https://evil.com/test', {
      headers: {
        'cf-connecting-ip': '47.111.21.195',
        'x-proxy-key': 'test-key'
      }
    });
    const env = { PROXY_KEY: 'test-key' };
    const res = await worker.fetch(req, env);
    assert.strictEqual(res.status, 403);
    assert.strictEqual(await res.text(), 'host not allowed: evil.com');
  });

  await t.test('allows whitelisted host', async () => {
    // Mock fetch to return a response
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      return new Response('mock response', {
        status: 200,
        headers: { 'content-type': 'text/plain' }
      });
    };

    try {
      const req = new Request('https://gh-proxy.test/https://github.com/test/repo', {
        headers: {
          'cf-connecting-ip': '47.111.21.195',
          'x-proxy-key': 'test-key'
        }
      });
      const env = { PROXY_KEY: 'test-key' };
      const res = await worker.fetch(req, env);
      assert.strictEqual(res.status, 200);
      assert.strictEqual(await res.text(), 'mock response');
      assert.strictEqual(res.headers.get('access-control-allow-origin'), '*');
      assert.strictEqual(res.headers.get('set-cookie'), null);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('strips incoming authorization header', async () => {
    let capturedHeaders = null;
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      capturedHeaders = options.headers;
      return new Response('ok', { status: 200 });
    };

    try {
      const req = new Request('https://gh-proxy.test/https://github.com/test/repo', {
        headers: {
          'cf-connecting-ip': '47.111.21.195',
          'x-proxy-key': 'test-key',
          'authorization': 'Bearer client-token',
          'x-custom': 'preserved'
        }
      });
      const env = { PROXY_KEY: 'test-key' };
      await worker.fetch(req, env);

      assert.strictEqual(capturedHeaders.get('authorization'), null);
      assert.strictEqual(capturedHeaders.get('x-custom'), 'preserved');
      assert.strictEqual(capturedHeaders.get('x-proxy-key'), null);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('injects PAT for hdot123-org private repos (Basic auth)', async () => {
    let capturedHeaders = null;
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      capturedHeaders = options.headers;
      return new Response('ok', { status: 200 });
    };

    try {
      const req = new Request('https://gh-proxy.test/https://github.com/hdot123-org/infra-core', {
        headers: {
          'cf-connecting-ip': '47.111.21.195',
          'x-proxy-key': 'test-key'
        }
      });
      const env = { PROXY_KEY: 'test-key', GH_PRIVATE_PAT: 'FAKE_TEST_PAT_12345' };
      await worker.fetch(req, env);

      // Should be Basic auth: base64("x-access-token:FAKE_TEST_PAT_12345")
      const expected = "Basic " + btoa("x-access-token:FAKE_TEST_PAT_12345");
      assert.strictEqual(capturedHeaders.get('authorization'), expected);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('does not inject PAT for other repos', async () => {
    let capturedHeaders = null;
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      capturedHeaders = options.headers;
      return new Response('ok', { status: 200 });
    };

    try {
      const req = new Request('https://gh-proxy.test/https://github.com/other-org/repo', {
        headers: {
          'cf-connecting-ip': '47.111.21.195',
          'x-proxy-key': 'test-key'
        }
      });
      const env = { PROXY_KEY: 'test-key', GH_PRIVATE_PAT: 'FAKE_TEST_PAT_12345' };
      await worker.fetch(req, env);

      assert.strictEqual(capturedHeaders.get('authorization'), null);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('does not inject PAT when GH_PRIVATE_PAT missing', async () => {
    let capturedHeaders = null;
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      capturedHeaders = options.headers;
      return new Response('ok', { status: 200 });
    };

    try {
      const req = new Request('https://gh-proxy.test/https://github.com/hdot123-org/infra-core', {
        headers: {
          'cf-connecting-ip': '47.111.21.195',
          'x-proxy-key': 'test-key'
        }
      });
      const env = { PROXY_KEY: 'test-key' };
      await worker.fetch(req, env);

      assert.strictEqual(capturedHeaders.get('authorization'), null);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('handles subpaths correctly for PAT injection', async () => {
    let capturedHeaders = null;
    let capturedUrl = null;
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      capturedUrl = url;
      capturedHeaders = options.headers;
      return new Response('ok', { status: 200 });
    };

    try {
      const req = new Request('https://gh-proxy.test/https://github.com/hdot123-org/infra-core.git/info/refs', {
        headers: {
          'cf-connecting-ip': '47.111.21.195',
          'x-proxy-key': 'test-key'
        }
      });
      const env = { PROXY_KEY: 'test-key', GH_PRIVATE_PAT: 'FAKE_TEST_PAT_12345' };
      await worker.fetch(req, env);

      const expected = "Basic " + btoa("x-access-token:FAKE_TEST_PAT_12345");
      assert.strictEqual(capturedHeaders.get('authorization'), expected);
      assert.strictEqual(capturedUrl, 'https://github.com/hdot123-org/infra-core.git/info/refs');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('preserves query string', async () => {
    let capturedUrl = null;
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      capturedUrl = url;
      return new Response('ok', { status: 200 });
    };

    try {
      const req = new Request('https://gh-proxy.test/https://github.com/test/repo?param=value', {
        headers: {
          'cf-connecting-ip': '47.111.21.195',
          'x-proxy-key': 'test-key'
        }
      });
      const env = { PROXY_KEY: 'test-key' };
      await worker.fetch(req, env);

      assert.strictEqual(capturedUrl, 'https://github.com/test/repo?param=value');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('handles different HTTP methods', async () => {
    let capturedMethod = null;
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      capturedMethod = options.method;
      return new Response('ok', { status: 200 });
    };

    try {
      const req = new Request('https://gh-proxy.test/https://github.com/test/repo', {
        method: 'POST',
        headers: {
          'cf-connecting-ip': '47.111.21.195',
          'x-proxy-key': 'test-key'
        }
      });
      const env = { PROXY_KEY: 'test-key' };
      await worker.fetch(req, env);

      assert.strictEqual(capturedMethod, 'POST');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await t.test('GET method does not send body', async () => {
    let capturedBody = null;
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      capturedBody = options.body;
      return new Response('ok', { status: 200 });
    };

    try {
      const req = new Request('https://gh-proxy.test/https://github.com/test/repo', {
        method: 'GET',
        headers: {
          'cf-connecting-ip': '47.111.21.195',
          'x-proxy-key': 'test-key'
        }
      });
      const env = { PROXY_KEY: 'test-key' };
      await worker.fetch(req, env);

      assert.strictEqual(capturedBody, undefined);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
