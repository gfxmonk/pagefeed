#!/usr/bin/env python

import wsgiref.handlers
from google.appengine.ext import webapp
from google.appengine.api import users
from google.appengine.ext.webapp import template

import os
import urllib
import cgi
from models import Page, UserID

class HttpError(Exception):
	def __init__(self, code, content=''):
		self.code = code
		self.content = ''

class BaseHandler(webapp.RequestHandler):
	def handle_exception(self, exc, *a, **k):
		if isinstance(exc, HttpError):
			self.error(exc.code)
			self.response.out.write(exc.content)
			return
		webapp.RequestHandler.handle_exception(self, exc, *a, **k)
		
	def user(self):
		user = users.get_current_user()
		if user:
			return user
		else:
			self.redirect(users.create_login_url(self.request.uri))
		
	def url(self):
		url = self.request.get('url')
		if url:
			return url
		raise HttpError(400)
	

class MainHandler(BaseHandler):
	def get(self):
		user = self.user()
		email = user.email()
		user_handle = UserID.get(email).handle
		uri = self.request.uri + 'feed/%s-%s/' % (user_handle, urllib.quote(email))
		
		template_values = {
			'name': user.nickname(),
			'pages': Page.find_all(user),
			'feed_link': uri,
		}
		path = os.path.join(os.path.dirname(__file__), 'index.html')
		self.response.out.write(template.render(path, template_values))

class FeedHandler(BaseHandler):
	# note: doesn't require a logged-in user()
	# authentication is handled by the secret (but uninportant) user handle
	# in addition to email address
	def get(self, handle, email):
		email = urllib.unquote(email)
		if not UserID.auth(email, int(handle)):
			raise HttpError(403, "invalid credentials... ")
		user = users.User(email)
		template_values = {
			'user': email,
			'pages': Page.find_all(user),
			'uri': self.request.uri,
		}
		path = os.path.join(os.path.dirname(__file__), 'feed.rss')
		self.response.out.write(template.render(path, template_values))

class PageHandler(BaseHandler):
	def _add(self, user, url):
		existing = Page.find(user, url)
		if existing is None:
			Page(owner=self.user(), url=url).put()
			return True
		return False

	def post(self):
		self._add(self.user(), self.url())
		self.redirect('/')

	def delete(self):
		page = Page.find(owner=self.user(), url=self.url())
		if page:
			page.delete()
			self.response.out.write("deleted")
			self.redirect('/')
		else:
			raise HttpError(404, "could not find saved page: %s" % (cgi.escape(self.url(),)))

class PageDeleteHandler(PageHandler):
	# alias for DELETE on PageHandler
	get = post = PageHandler.delete

def main():
	application = webapp.WSGIApplication([
		('/', MainHandler),
		('/page/', PageHandler),
		('/page/del/', PageDeleteHandler),
		(r'/feed/(\d+)-([^/]+)/', FeedHandler),
		], debug=True)
	wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
	main()
