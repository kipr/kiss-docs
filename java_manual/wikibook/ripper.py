import lxml.html
import urllib.request
import urllib.parse
import lxml.html.clean
import copy
import hashlib
import re
import os

class MediawikiRipper:
    def __init__(self, site_url="en.wikipedia.org", opener=None,
                 page_processor=None, css_skin="modern"):
        self.site_url = site_url
        if opener is None:
            opener = urllib.request.build_opener()
            opener.addheaders = [('User-agent', 'Mozilla/5.0')]
        self.opener = opener
        if page_processor is None:
            page_processor = PageParser
        self.page_processor = page_processor(self)
        self.processed_pages = set()
        self.page_queue = set()
        self.css_skin = css_skin
        self.queue(self.css_url)
    
    def queue(self, *items):
        if len(items) == 1 and not isinstance(items[0], str):
            items = items[0]
        items = list(items)
        for i in range(len(items)): # write wiki page urls in the right format
            items[i] = self.simplify_url(items[i])
        self.page_queue.update(items)
        self.page_queue -= self.processed_pages
    
    def process_queue(self):
        while self.page_queue:
            url = self.page_queue.pop()
            self.download(url)
            self.processed_pages.add(url)
    
    def will_have_local(self, url):
        url = self.simplify_url(url)
        return url in self.page_queue or url in self.processed_pages
    
    def simplify_url(self, url):
        is_wiki_page = self.is_wiki_page(url)
        if is_wiki_page: return is_wiki_page
        return url
    
    def is_wiki_page(self, url):
        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.scheme != "http" and parsed_url.scheme != "https":
            return url
        if parsed_url.path == "/w/index.php":
            parsed_query = urllib.parse.parse_qs(parsed_url.query)
            if "title" in parsed_query:
                return urllib.parse.unquote(parsed_query["title"][0])
        if not parsed_url.path:
            return False
        split_path = parsed_url.path.split("/")[1:] # drop the /leading/slash
        if split_path[0] == "wiki" and not split_path[1].startswith("File:"):
            return urllib.parse.unquote("/".join(split_path[1:]))
        return False
    
    def _load_wiki_page(self, wiki_page):
        url = "http://%s/w/index.php?title=%s&printable=yes" % \
              (self.site_url, urllib.parse.quote(wiki_page))
        return lxml.html.tostring(
            self.page_processor.get_new_page(
                lxml.html.parse(
                    self.opener.open(url)
                )
            )
        ).decode()
    
    def url_to_filename(self, url):
        is_wiki_page = self.is_wiki_page(url)
        if is_wiki_page:
            return self._wiki_page_to_filename(is_wiki_page)
        if url == self.css_url:
            return self.css_filename
        # handle various unknown files
        # use a hash to ensure uniqueness with the same filename
        file_name = re.match(r".*/(.+?)/?\Z", url).group(1)
        extension = re.match(r".*?(\.([a-zA-Z0-9]+))?\Z", file_name).group(2)
        if extension in ("jpg", "jpeg", "png", "gif", "svg"):
            folder = "thumbs"
        else:
            folder = "misc"
        hashed_url = hashlib.md5(url.encode()).hexdigest()
        return "%s/%s_%s" % (folder, hashed_url[:min(5, len(hashed_url))],
                             file_name)
    
    def _wiki_page_to_filename(self, wiki_page):
        return "pages/%s.html" % wiki_page
    
    def _save_as(self, file_name, contents):
        try:
            os.makedirs(re.match(r"(.*)/.+?\Z", file_name).group(1))
        except OSError:
            # folder already exists?
            pass
        if isinstance(contents, str):
            file_handler = open(file_name, "w")
        else:
            file_handler = open(file_name, "wb")
        try:
            file_handler.write(contents.read())
        except:
            file_handler.write(contents)
        file_handler.close()
    
    def download(self, url):
        is_wiki_page = self.is_wiki_page(url)
        if is_wiki_page:
            return self._download_wiki_page(is_wiki_page)
        return self._download_file(url)
    
    def _download_file(self, url):
        self._save_as(self.url_to_filename(url), self.opener.open(url))
    
    def _download_wiki_page(self, wiki_page):
        wiki_page = self.simplify_url(wiki_page)
        self._save_as(self._wiki_page_to_filename(wiki_page),
                      self._load_wiki_page(wiki_page))
    
    def get_css_url(self):
        return "https://bits.wikimedia.org/%s/load.php?" \
               "debug=true&lang=en&modules=skins.vector|mediawiki.legacy.commonPrint&only=styles&skin=%s" % \
               (self.site_url, self.css_skin)
    
    css_url = property(get_css_url)
    
    def get_css_filename(self):
        return "misc/%s.css" % self.css_skin
    
    css_filename = property(get_css_filename)

class PageParser:
    def __init__(self, manager):
        self.manager = manager
    
    def get_title(self, lxml_page):
        return str(lxml_page.xpath("id('firstHeading')")[0].text_content())
    
    def get_content(self, lxml_page):
        return self._content_rewrite_links(
            self._content_clean(
                copy.deepcopy(lxml_page.xpath("id('bodyContent')")[0])
            )
        )
    
    def get_new_page(self, lxml_page):
        from lxml.html import builder as E
        title = self.get_title(lxml_page)
        lxml_content = self.get_content(lxml_page)
        stylesheet_rel_filename = self.make_paths_relative(
            self.manager.url_to_filename(lxml_content.base_url),
            self.manager.css_filename
        )
        return E.HTML(
            E.HEAD(
                E.TITLE(title),
                E.LINK(rel="stylesheet", href=stylesheet_rel_filename,
                       type="text/css", media="all")
            ),
            E.BODY(
                E.DIV(
                    E.H1(title, id="firstHeading", **{"class":"firstHeading"}),
                    lxml_content,
                    id="content"
                ),
                **{"class":"mediawiki"}
            )
        )
    
    def _content_clean(self, lxml_content):
        css_removes = "#siteSub", "#contentSub", "#jump-to-nav", "#catlinks", \
                      "#mw-data-after-content", "#searchbox", ".noprint", \
                      ".metadata", ".printfooter"
        for css_expression in css_removes:
            for tag in lxml_content.cssselect(css_expression):
                tag.drop_tree()
        lxml.html.clean.Cleaner(
            comments=True, style=False, processing_instructions=False,
            page_structure=False, remove_unknown_tags=False,
            safe_attrs_only=False
        )(lxml_content)
        return lxml_content
    
    def make_paths_relative(self, cur_filename, new_filename):
        cur_filename = cur_filename.split("/")
        new_filename = new_filename.split("/")
        while cur_filename[0] == new_filename[0] and len(cur_filename) > 1:
            del cur_filename[0]
            del new_filename[0]
        return ("../" * (len(cur_filename) - 1)) + "/".join(new_filename)
    
    def _content_rewrite_links(self, lxml_content):
        lxml_content.make_links_absolute(lxml_content.base_url)
        
        self._content_build_queue(lxml_content)
        
        def rewrite_link(url):
            if not self.manager.will_have_local(url):
                return url
            cur_filename = self.manager.url_to_filename(lxml_content.base_url)
            new_filename = self.manager.url_to_filename(url)
            return self.make_paths_relative(cur_filename, new_filename)
            
        lxml_content.rewrite_links(rewrite_link)
        
        return lxml_content
    
    def _content_build_queue(self, lxml_content):
        for image_element in lxml_content.cssselect("img"):
            self.manager.queue(image_element.attrib["src"])

ripper = MediawikiRipper("en.wikibooks.org")
rip_list = """Java_Programming/Java_Beans
Java_Programming/Language_Fundamentals
Java_Programming/Collections
Java_Programming/Exceptions
Java_Programming/Reflection
Java_Programming/Keywords/public
Java_Programming/Keywords
Java_Programming/Literals/Numeric_Literals/Floating_Point_Literals
Java_Programming/Syntax/Whitespace
Java_Programming/Reflection/Accessing_Private_Features_with_Reflection
Java_Programming/Reflection/Dynamic_Invocation
Java_Programming/Reflection/Overview
Java_Programming/Reflection/Dynamic_Class_Loading
Java_Programming/Collection_Classes
Java_Programming/Creating_Objects
Java_Programming/Data_and_Variables
Java_Programming/Defining_Classes
Java_Programming/Destroying_Objects
Java_Programming/Execution
Java_Programming/Interfaces
Java_Programming/Keywords/assert
Java_Programming/Keywords/final
Java_Programming/Keywords/private
Java_Programming/Keywords/transient
Java_Programming/Statements/if
Java_Programming/Struts/Struts_Tag_Library
Java_Programming/Syntax/Unicode_Escape_Sequences
Java_Programming/Keywords/boolean
Java_Programming/Keywords/for
Java_Programming/Literals/Boolean_Literals/false
Java_Programming/Keywords/class
Java_Programming/Keywords/int
Java_Programming/Keywords/static
Java_Programming/Literals/Boolean_Literals/true
Java_Programming/Literals/null
Java_Programming/Math
Java_Programming/Nested_Classes
Java_Programming/Remote_Method_Invocation
Java_Programming/Syntax/Unicode_Source
Java_Programming/Throwing_and_Catching_Exceptions
Java_Programming/Preventing_NullPointerException
Java_Programming/Statements
Java_Programming/Keywords/protected
Java_Programming/Keywords/package
Java_Programming/Keywords/import
Java_Programming/Keywords/new
Java_Programming/Keywords/if
Java_Programming/Keywords/goto
Java_Programming/Keywords/const
Java_Programming/Keywords/this
Java_Programming/Keywords/abstract
Java_Programming/Keywords/else
Java_Programming/Keywords/while
Java_Programming/Keywords/extends
Java_Programming/Keywords/implements
Java_Programming/Keywords/throws
Java_Programming/Keywords/do
Java_Programming/Keywords/case
Java_Programming/Keywords/switch
Java_Programming/Keywords/break
Java_Programming/Keywords/default
Java_Programming/Keywords/continue
Java_Programming/Keywords/interface
Java_Programming/Keywords/try
Java_Programming/Keywords/catch
Java_Programming/Keywords/throw
Java_Programming/Keywords/instanceof
Java_Programming/Keywords/finally
Java_Programming/Keywords/synchronized
Java_Programming/Keywords/volatile
Java_Programming/Keywords/strictfp
Java_Programming/Keywords/native
Java_Programming/Keywords/char
Java_Programming/Keywords/short
Java_Programming/Keywords/long
Java_Programming/Keywords/byte
Java_Programming/Keywords/float
Java_Programming/Keywords/double
Java_Programming/Keywords/enum
Java_Programming/Threads
Java_Programming/Keywords/return
Java_Programming/Keywords/void
Java_Programming/Classes,_Objects_and_Types
Java_Programming/Threads_and_Runnables
Java_Programming/Exceptions/NullPointerException
Java_Programming/Operators
Java_Programming/Applets/Event_Listeners
Java_Programming/Unchecked_Exceptions
Java_Programming/Checked_Exceptions
Java_Programming/Overloading_Methods_and_Constructors
Java_Programming/Using_Static_Members
Java_Programming/Generics
Java_Programming/Blocks
Java_Programming/Swing
Java_Programming/Java_Foundations
Java_Programming/Java_Overview
Java_Programming/Applets/Overview
Java_Programming/Applets/User_Interface
Java_Programming/Applets/Graphics_and_Media
Java_Programming/Client_Server
Java_Programming/Design_Patterns
Java_Programming/Getting_Started
Java_Programming/Classes_and_Objects
Java_Programming/Annotations/Introduction
Java_Programming/Annotations/Meta-Annotations
Java_Programming/Annotations/Compiler_and_Annotations
Java_Programming/Byte_Code
Java_Programming/Nesting_Exceptions
Java_Programming/Stack_trace
Java_Programming/Networking
Java_Programming/Concurrent_Programming
Java_Programming/JavaSpaces
Java_Programming/Introduction
Java_Programming/Spring_framework
Java_Programming/Canvas
Java_Programming/Graphics/Drawing_shapes
Java_Programming/JSP
Java_Programming/Java_IDEs
Java_Programming/Q&A
Java_Programming/Random
Java_Programming/Regular_Expressions
Java_Programming/Syntax/Comments
Java_Programming/Index
Java_Programming/Glossary
Java_Programming/Access_Modifiers
Java_Programming/Annotations
Java_Programming/Annotations/Custom_Annotations
Java_Programming/How_to_use_this_book
Java_Programming/Struts
Java_Programming/Types/Numeric_Primitives
Java_Programming/Event_Handling
Java_Programming/Methods
Java_Programming/RMI-IIOP
Java_Programming/JavaBeans/Introduction_to_JavaBeans
Java_Programming/Basic_IO
Java_Programming/Flow_control
Java_Programming/Compilation
Java_Programming/Whitespace
Java_Programming/Topics
Java_Programming/Understanding_a_Java_Program/Javadoc_and_other_comments
Java_Programming/Libraries
Java_Programming/JavaBeans
Category:Java_Programming/Keywords
Java_Programming/Literals
Java_Programming/Literals/Boolean_literals
Java_Programming/Literals/Numeric_Literals/Integer_Literals
Java_Programming/Literals/Numeric_Literals
Java_Programming/Literals/Numeric_Literals/Character_Literals
Java_Programming/Keywords/super
Java_Programming/API/java.lang.String
Java_Programming/API/java.lang.Class
Java_Programming/Packages
Java_Programming/Applets
Java_Programming/Basic_Synchronization
Java_Programming/Java_Security
Java_Programming/EJB
Java_Programming/Tutorials/Notepad
Java_Programming/Comparing_Objects
Java_Programming/Jini
Java_Programming/Tutorials
Java_Programming/Applets/ActionListener
Java_Programming/Getting_Started/Compilation
Java_Programming/Graphics
Java_Programming/Database_Programming
Java_Programming/Class_Loading
Java_Programming/SwingLayouts
Java_Programming/SwingLargeExamples
Java_Programming/FirstExamples
Java_Programming/Events_and_Buttons
Java_Programming/IntroToStreams&Outputting_Text
Java_Programming/Reading_Text_Input
Java_Programming/Responsive_Swing_Application
Java_Programming/Basic_IO/Introduction_to_Streams
Java_Programming/Types/boolean
Java_Programming/Graphics/Drawing_complex_shapes
Category:Java_Programming/Templates
Java_Programming/Literals/String_Literals
Java_Programming/Large_numbers
Java_Programming/Object-Oriented_Programming_Basics
Java_Programming/Object-Oriented_Programming_Basics/What_is_an_Object?
Java_Programming/Authors_&_Contributors
Java_Programming/Beginning_Java
Java_Programming/Networking/Basics
Java_Programming/Files_and_Streams
Java_Programming/Applets/MouseListener
Java_Programming/Todo
Java_Programming/Understanding_a_Java_Program
Java_Programming/Getting_Started/Installation
Java_Programming/Arrays
Java_Programming/API/java.lang.Object
Java_Programming/Print_version
Java_Programming/History
Java_Programming/Links
Java_Programming/Syntax
Java_Programming
Java_Programming/Types
Java_Programming/About_This_Book
Java_Programming/The_Java_Platform
Java_Programming/Random_numbers
Java_Programming/Getting_started
Java_Programming/Variables
Java_Programming/Basic_arithmetic
Java_Programming/Mathematical_functions"""
ripper.queue(rip_list.split("\n"))
ripper.process_queue()
