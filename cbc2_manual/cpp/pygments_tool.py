import sys
import pygments
import pygments.formatters
import pygments.lexers
import re

class HtmlHandler:
    def __init__(self, html_source):
        self.html_source = html_source
        self._regex = re.compile(
            r"(?P<start_tag>\<\s*(?P<tag_name>pygm(ents)?).*?\>)"
            r"(?P<contents>.*?)"
            r"(?P<end_tag>\<.*?\s*pygm(ents)?\s*>)", re.IGNORECASE | re.DOTALL
        )
        self._attr_regex = re.compile(r"""([a-z0-9]+)\s*=\s*["'](.+?)["']""", 
                                      re.IGNORECASE | re.DOTALL)
        self.lookup_index = 0
    
    def __iter__(self):
        return self
    
    def next(self): # Python 2
        tag_match = self._regex.search(self.html_source, self.lookup_index)
        if not tag_match:
            raise StopIteration()
        tag_string = tag_match.group(0)
        self.lookup_index = tag_match.end()
        attributes = {
            i.group(1).lower():i.group(2).lower()
            for i in self._attr_regex.finditer(tag_match.group("start_tag"))
        }
        return HtmlElement(self, tag_string, tag_match.start(),
                           tag_match.group("tag_name"), attributes,
                           tag_match.group("contents"))
    
    def __next__(self): # Python 3
        return self.next()

class HtmlElement:
    def __init__(self, parent, string, start_index, tag_name, attributes,
                 contents):
        self._parent = parent
        self._string = string
        self._start_index = start_index
        self.tag_name = tag_name
        self.attributes = attributes
        self.contents = contents
    
    def replace(self, replacement_string):
        source = self._parent.html_source
        self._parent.html_source = source[:self._start_index] + \
                                   replacement_string + \
                                   source[self._start_index +
                                          len(self._string):]
        self._parent.lookup_index += \
            len(replacement_string) - len(self._string)

formatter = pygments.formatters.HtmlFormatter(cssclass="pygments")
html_source = sys.stdin.read()
handler = HtmlHandler(html_source)
default_lang = sys.argv[1] if len(sys.argv) > 1 else None

for element in handler:
    language = element.attributes["language"] \
               if "language" in element.attributes else default_lang
    code = element.contents
    
    # strip line-start spacing
    lead_spacing_match = re.match(r"\s*?\n(\s*)", code)
    lead_spacing = lead_spacing_match.group(1) if lead_spacing_match else ""
    code = "\n".join(
        i[len(lead_spacing):] if i.startswith(lead_spacing) else i
        for i in code.split("\n")
    )
    code = code.strip()
    
    lexer = pygments.lexers.get_lexer_by_name(language) \
            if language else pygments.lexers.guess_lexer(code)
    formatted_html_source = pygments.highlight(code, lexer, formatter)
    
    inline_mode = element.tag_name == "pygm"
    if "display" in element.attributes:
        inline_mode = element.attributes["display"] == "inline"
    
    if inline_mode:
        # Hack up the generated html to make it work inlined
        tag = r"\<\s*%s"
        closing_tag = r"\<\s*/\s*%s\s*\>"
        formatted_html_source = re.sub(tag % "div", "<span",
                                       formatted_html_source)
        formatted_html_source = re.sub(closing_tag % "div", "</span>",
                                       formatted_html_source)
        formatted_html_source = re.sub(tag % "pre", "<code",
                                       formatted_html_source)
        formatted_html_source = re.sub(closing_tag % "pre", "</code>",
                                       formatted_html_source)
        formatted_html_source = formatted_html_source.replace("\n", "")
    
    element.replace(formatted_html_source)

print(handler.html_source)
