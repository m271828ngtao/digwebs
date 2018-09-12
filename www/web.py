#!/usr/bin/env python
'''
A simple, lightweight, WSGI-compatible web framework.
'''

__author__ = 'SLZ'

# import build-in modules
import os
import sys
import time
import datetime
import threading
import logging
import traceback
import hashlib
import functools
from io import StringIO
# import custom modules
from .common import Dict
from .errors import notfound, HttpError, RedirectError
from .request import Request
from .response import Response
from .template import Template, Jinja2TemplateEngine

# thread local object for storing request and response:
ctx = threading.local()


class digwebs(object):
    def __init__(self, document_root, **kw):
        '''
        Init a digwebs.

        Args:
          document_root: document root path.
        '''
        self._running = False
        self._document_root = document_root
        self._template_engine = None

        def datetime_filter(t):
            delta = int(time.time() - t)
            if delta < 60:
                return u'1分钟前'
            if delta < 3600:
                return u'%s分钟前' % (delta // 60)
            if delta < 86400:
                return u'%s小时前' % (delta // 3600)
            if delta < 604800:
                return u'%s天前' % (delta // 86400)
            dt = datetime.datetime.fromtimestamp(t)
            return u'%s年%s月%s日' % (dt.year, dt.month, dt.day)

        self.template_engine = Jinja2TemplateEngine(
            os.path.join(document_root, 'views'))
        self.template_engine.add_filter('datetime', datetime_filter)
        self.middleware = []

    def _check_not_running(self):
        if self._running:
            raise RuntimeError('Cannot modify digwebs when running.')

    @property
    def template_engine(self):
        return self._template_engine

    @template_engine.setter
    def template_engine(self, engine):
        self._check_not_running()
        self._template_engine = engine

    def init_middlewares(self):
        for f in os.listdir(self._document_root + r'/middlewares'):
            if f.endswith('.py'):
                import_module = f.replace(".py", "")
                m = __import__('middlewares', globals(), locals(),
                               [import_module])
                s_m = getattr(m, import_module)
                fn = getattr(s_m, import_module, None)
                if fn is not None and callable(
                        fn) and not import_module.endswith('__'):
                    self.middleware.append(fn())

        def take_second(elem):
            return elem[1]

        self.middleware.sort(key=take_second)

    def run(self, port=9999, host='127.0.0.1'):
        from wsgiref.simple_server import make_server
        logging.info('application (%s) will start at %s:%s...' %
                     (self._document_root, host, port))
        server = make_server(host, port, self.get_wsgi_application())
        server.serve_forever()

    def get_wsgi_application(self):
        self._check_not_running()
        self._running = True

        _application = Dict(document_root=self._document_root)

        def fn_route():
            def route_entry(context, next):
                def dispatch(i):
                    fn = self.middleware[i][0]
                    if i == len(self.middleware):
                        fn = next
                    return fn(context, lambda: dispatch(i + 1))

                return dispatch(0)

            return route_entry

        fn_exec = fn_route()

        def wsgi(env, start_response):
            ctx.application = _application
            ctx.request = Request(env)
            response = ctx.response = Response()
            try:
                r = fn_exec(ctx, None)
                if isinstance(r, Template):
                    tmp = []
                    tmp.append(self._template_engine(r.template_name, r.model))
                    r = tmp
                if isinstance(r, str):
                    tmp = []
                    tmp.append(r.encode('utf-8'))
                    r = tmp
                if r is None:
                    r = []
                start_response(response.status, response.headers)
                return r
            except RedirectError as e:
                response.set_header('Location', e.location)
                start_response(e.status, response.headers)
                return []
            except HttpError as e:
                start_response(e.status, response.headers)
                return ['<html><body><h1>', e.status, '</h1></body></html>']
            except Exception as e:
                logging.exception(e)
                '''
                if not configs.get('debug',False):
                    start_response('500 Internal Server Error', [])
                    return ['<html><body><h1>500 Internal Server Error</h1></body></html>']
                '''
                exc_type, exc_value, exc_traceback = sys.exc_info()
                fp = StringIO()
                traceback.print_exception(
                    exc_type, exc_value, exc_traceback, file=fp)
                stacks = fp.getvalue()
                fp.close()
                start_response('500 Internal Server Error', [])
                return [
                    r'''<html><body><h1>500 Internal Server Error</h1><div style="font-family:Monaco, Menlo, Consolas, 'Courier New', monospace;"><pre>''',
                    stacks.replace('<', '&lt;').replace('>', '&gt;'),
                    '</pre></div></body></html>'
                ]
            finally:
                del ctx.application
                del ctx.request
                del ctx.response

        return wsgi

    def get(self, path):
        '''
        A @get decorator.

        @get('/:id')
        def index(id):
            pass

        >>> @get('/test/:id')
        ... def test():
        ...     return 'ok'
        ...
        >>> test.__web_route__
        '/test/:id'
        >>> test.__web_method__
        'GET'
        >>> test()
        'ok'
        '''

        def _decorator(func):
            func.__web_route__ = path
            func.__web_method__ = 'GET'
            return func

        return _decorator

    def post(self, path):
        '''
        A @post decorator.

        >>> @post('/post/:id')
        ... def testpost():
        ...     return '200'
        ...
        >>> testpost.__web_route__
        '/post/:id'
        >>> testpost.__web_method__
        'POST'
        >>> testpost()
        '200'
        '''

        def _decorator(func):
            func.__web_route__ = path
            func.__web_method__ = 'POST'
            return func

        return _decorator

    def put(self, path):
        '''
        A @put decorator.
        '''

        def _decorator(func):
            func.__web_route__ = path
            func.__web_method__ = 'PUT'
            return func

        return _decorator

    def delete(self, path):
        '''
        A @delete decorator.
        '''

        def _decorator(func):
            func.__web_route__ = path
            func.__web_method__ = 'DELETE'
            return func

        return _decorator

    def view(self, path):
        '''
        A view decorator that render a view by dict.

        >>> @view('test/view.html')
        ... def hello():
        ...     return dict(name='Bob')
        >>> t = hello()
        >>> isinstance(t, Template)
        True
        >>> t.template_name
        'test/view.html'
        >>> @view('test/view.html')
        ... def hello2():
        ...     return ['a list']
        >>> t = hello2()
        Traceback (most recent call last):
        ...
        ValueError: Expect return a dict when using @view() decorator.
        '''

        def _decorator(func):
            @functools.wraps(func)
            def _wrapper(*args, **kw):
                r = func(*args, **kw)
                if isinstance(r, dict):
                    logging.info('return Template')
                    return Template(path, **r)
                raise ValueError(
                    'Expect return a dict when using @view() decorator.')

            return _wrapper

        return _decorator


if __name__ == '__main__':
    sys.path.append('.')
    import doctest
    doctest.testmod()
