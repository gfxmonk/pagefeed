from test_helpers import *
from models import page
from models.page import Page, Content
from google.appengine.ext import deferred
from google.appengine.ext import db

some_url = 'http://localhost/dontcare'

class CleanDBTest(TestCase):
	def setUp(self):
		super(CleanDBTest, self).setUp()
		db.delete(Page.all())
		db.delete(Content.all())

class PageLifecycleTest(CleanDBTest):
	def setUp(self):
		super(PageLifecycleTest, self).setUp()
		self.defer_mock = mock(deferred).defer
		when(deferred).defer(*any_args, **any_kwargs).then_return(None)

	def test_page_should_start_with_no_content(self):
		p = Page(url=some_url, owner=a_user)
		self.assertEquals(p.content, None)
	
	def test_page_should_launch_tasks_to_populate_data(self):
		p = Page(url=some_url, owner=a_user)
		p.put()
		expect(page.Transform).process(p)
		expect(deferred).defer(page.task_extract_content, 'native', p.key())
		expect(deferred).defer(page.task_extract_content, 'view_text', p.key())
		p.start_content_population()

	def test_should_log_error_and_ignore_transforms_if_they_fail(self):
		modify(page).content_extractors = []

		p = Page(url=some_url, owner=a_user)

		expect(page.Transform).process(p).and_raise(page.TransformError("transform failed"))
		expect(p).error("transform failed")
		expect(deferred).defer(page.task_extract_content, *any_args).twice()

		p.start_content_population()
	
	def test_reset_should_clear_all_content(self):
		p = Page(url=some_url, owner=a_user)
		p.content = "content!"
		p.raw_content = "raw content!"
		p.title = "title"
		
		p.update(force=True)
		self.assertEquals(p.content, None)
		self.assertEquals(p.raw_content, None)
		self.assertEqual(p.title, "title")

	def test_store_best_content_should_do_nothing_if_not_all_processors_have_completed(self):
		p = Page(url=some_url, owner=a_user)
		p.put()
		modify(page).content_extractors = [1,2, 3, 4, 5, 6]
		when(Content).for_url(p.url).then_return([Content(url=some_url)])

		page.task_store_best_content(p.key())
		p = Page.get(p.key())
		self.assertEquals(p._title, None)
		self.assertEquals(p.content, None)

	def test_store_best_content_should_store_empty_values_if_forced(self):
		p = Page(url=some_url, owner=a_user)
		p.put()
		modify(page).content_extractors = [1,2, 3, 4, 5, 6]
		when(Content).for_url(p.url).then_return([])

		page.task_store_best_content(p.key(), force=True)
		p = Page.get(p.key())
		self.assertEquals(p._title, '[localhost saved item]')
		self.assertEquals(p.content, '')

	def test_store_best_content_should_do_so_if_all_extractors_are_complete(self):
		p = Page(url=some_url, owner=a_user)
		p.put()
		modify(page).content_extractors = [1,2]

		best_content = Content(url=some_url, title='best title', body='best body')
		worst_content = Content(url=some_url)

		contents = [best_content, worst_content]
		map(lambda x: expect(x).delete(), contents)

		when(Content).for_url(p.url).then_return(contents)

		page.task_store_best_content(p.key())

		p = Page.get(p.key())
		self.assertEquals(p.title, "best title")
		self.assertEquals(p.content, "best body")
	
	def test_store_best_content_should_do_nothing_if_content_is_already_set(self):
		p = Page(url=some_url, owner=a_user, content='some content')
		p.put()

		expect(Content).for_url.never().and_return([])

		page.task_store_best_content(p.key())

	
class PageTest(CleanDBTest):
	def test_find_complete_should_skip_incomplete_pages(self):
		incomplete = Page(url=some_url, owner=a_user)
		complete = Page(url=some_url, owner=a_user, content='')
		[x.put() for x in (incomplete, complete)]
		pages = list(Page.find_complete(a_user))
		self.assertEquals(len(pages), 1)
		self.assertEqual(pages[0].key(), complete.key())

	def test_should_load_well_formed_page(self):
		content = """
			<html>
			<title>the title!</title>
			<body>the body!</body>
			</html>
			"""
		result = mock('result')
		modify(result).children(status_code=200, content=content)
		url = 'http://localhost/some/path'
		expect(page).fetch(url, *any_args).and_return(result)
		
		p = new_page(url=url)
		self.assertEqual(p.title, 'the title!')
		self.assertEqual(p.content, '<body>the body!</body>')
		self.assertFalse(p.errors)
		
	def test_should_omit_page_fragment_from_request(self):
		result = mock('result')
		modify(result).children(status_code=200, content='blah')
		url = 'http://localhost/some/path'
		full_url = url + "#anchor"
		expect(page).fetch(url).and_return(result)
		
		p = new_page(url=full_url)
		self.assertEqual(p.url, full_url)
		self.assertEqual(p.content, 'blah')
		self.assertFalse(p.errors)
		

	def test_should_absoluteize_links_and_images(self):
		content = """
			<html>
			<title>the title!</title>
			<body>
				<a href="rel.html">rel</a>
				<a href="/path/to/pathed.html">pathed</a>
				<a href="http://google.com/abs.html">abs</a>
				<img src="/path/to/path2.jpg" />
			</body>
			</html>
			"""
		result = mock('result').with_children(status_code=200, content=content)
		url =      'http://localhost/some/path/to_page.html'
		rel_base = "http://localhost/some/path/"
		base =     "http://localhost/"
		mock_on(page).fetch.is_expected.with_(url).returning(result.raw)
		
		p = new_page(url=url)
		self.assertFalse(p.errors)
		print p.content
		self.assertTrue('<a href="%srel.html">' % rel_base in p.content)
		self.assertTrue('<a href="%spath/to/pathed.html">' % base in p.content)
		self.assertTrue('<a href="http://google.com/abs.html">' in p.content)
		self.assertTrue('<img src="%spath/to/path2.jpg" />' % base in p.content)

	def test_should_remove_a_bunch_of_unwanted_html_attributes(self):
		stub_result("""
				<html>
					<p style="border-color:#ff; background:#fff;" COLOR="foo" alt="lala">
						<img src="http://localhost/blah" width  =  100 height=  20px />
						<div bgcolor=foo>
							so then style=none should not be stripped
							<span bgcolor-andthensome="not_strippped"></span>
						</div>
					</p>
				</html>
			""")
		p = new_page()
		expected_html = """
				<html>
					<p alt="lala">
						<img src="http://localhost/blah" />
						<div>
							so then style=none should not be stripped
							<span bgcolor-andthensome="not_strippped"></span>
						</div>
					</p>
				</html>
			"""
		print "ACTUAL: " + p.content
		print '-----'
		print "EXPECTED: " + expected_html
		self.assertEqual(p.content.strip().replace('\t',''), expected_html.strip().replace('\t',''))
	
	def test_should_fall_back_to_a_default_title_containing_host(self):
		stub_result("<html><body>no title...</body></html>")
		p = new_page(url="http://google.com/blah")
		self.assertEqual(p.title, '[google.com saved item]')
		self.assertFalse(p.errors)
	
	@pending("cant insert failure condition properly...")
	def test_should_fall_back_to_a_default_title_if_no_host_available(self):
		stub_result("<html><body>no title...</body></html>")
		p = page.Page(url='http://localhost', owner=a_user)
		mock_on(p)._get_host.raising(StandardError)
		p.put()
		
		self.assertEqual(p.title, '[pagefeed saved item]')
		self.assertTrue("no title..." in p.content)
		self.assertFalse(p.errors)

	def test_should_fall_back_to_entire_html_if_it_has_no_body(self):
		html = "<html><title>no body</title></html>"
		stub_result(html)
		p = new_page()
		self.assertEqual(p.title, 'no body')
		self.assertEqual(p.content, html)
		self.assertFalse(p.errors)


	def test_should_discard_html_on_completely_unparseable(self):
		html = "<html></scr + ipt>"
		stub_result(html)
		p = new_page()
		self.assertEqual(p.content, '')
		self.assertTrue(p.errors)
	
	def test_should_strip_out_script_and_style_and_link_tags(self):
		html = "<html><body><script></script><style></style><link /></body>"
		stub_result(html)
		p = new_page()
		self.assertEqual(p.content, "<body></body>")
		self.assertFalse(p.errors)
	
	def test_should_apply_all_matching_transforms(self):
		filter1 = mock('filter1')
		filter2 = mock('filter2')
		filters = [filter1.raw, filter2.raw]

		p = page.Page(owner=a_user, url='http://sub.localhost.com/some/path/to/file.html')
		response = mock('response').with_children(status_code=200, content='initial content')
		mock_on(page).fetch.returning(response.raw)

		mock_on(Transform).find_all.with_(user=a_user, host='sub.localhost.com').is_expected.returning(filters)
		filter1.expects('apply').with_(p)
		filter2.expects('apply').with_(p)
		
		p.put()

	def test_should_fetch_content_from_new_url(self):
		old_url = 'http://old_url'
		new_url = 'http://new_url'
		p = new_page(content='initial content', url=old_url)

		response = mock('response').with_children(status_code=200, content='new content')
		mock_on(page).fetch.is_expected.with_(new_url).returning(response.raw)
		p.replace_with_contents_from(new_url)

		self.assertEqual(p.url, old_url)
		self.assertEqual(p.content, 'new content')
	
	@ignore
	def test_should_extract_xpath_elements(self):
		pass
	
	def test_should_note_an_error_when_download_fails(self):
		stub_result('', status_code = 400)
		p = new_page()
		self.assertTrue(p.errors)

	def test_should_retry_a_failed_download_on_update(self):
		stub_result('', status_code=404)
		mock_on(page).fetch.is_expected.twice

		p = new_page()
		p.update()

	def test_should_not_retry_a_successful_download_on_update(self):
		stub_result('')
		mock_on(page).fetch.is_expected.once

		p = new_page()
		p.update()

	@ignore
	def test_should_update_date_on_fetch(self):
		pass

	def test_should_retry_a_successful_download_on_update_if_forced(self):
		stub_result('')
		mock_on(page).fetch.is_expected.twice

		p = new_page()
		p.update(force=True)

	def test_should_render_as_html(self):
		url = 'http://my_url/base_path/resource'
		p = new_page('<title>t</title><body>b</body>', url=url)
		self.assertEqual(p.html.strip(), '<body>b</body>')

	def test_rendered_page_should_not_include_unparseable_html(self):
		url = 'http://my_url'
		orig_html = '<title>t</title><body>b<scr + ipt /></body>'

		p = new_page(orig_html, url=url)
		html = p.html
		self.assertTrue('an error occurred' in html, html)
		self.assertFalse(orig_html in html, html)

	def test_should_have_soup_and_host_attributes(self):
		p = new_page('<body><p>woo!</p></body>', url='http://google.com/some/page')
		self.assertEqual(p.host, 'google.com')
		self.assertEqual(p.soup.body.p.string, 'woo!')

	def test_should_have_base_href_attribute(self):
		def assert_base(url, expected_base):
			self.assertEqual(new_page(content='', url=url).base_href, expected_base)

		assert_base('http://localhost/aa/bbbb/c', 'http://localhost/aa/bbbb/')
		assert_base('http://localhost/aa', 'http://localhost/')
		assert_base('http://localhost/', 'http://localhost/')
		assert_base('http://localhost', 'http://localhost/')

	def test_should_accept_multiline_titles(self):
		p = new_page("<title>foo\nbar</title>")
		self.assertEqual(p.title, "foo bar")


def new_page(content=None, url=some_url):
	p = page.Page(url=url, owner=a_user)
	if content is None:
		p.put()
	else:
		p.populate_content(content)
	return p

def stub_result(content, status_code=200):
	result = mock('result').with_children(status_code=status_code, content=content)
	mock_on(page).fetch.returning(result.raw)
	return result


