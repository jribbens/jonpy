# $Id$

import sys, re, os, Cookie, errno
try:
  import cStringIO as StringIO
except ImportError:
  import StringIO

"""Object-oriented CGI interface."""


class Error(Exception):
  """The base class for all exceptions thrown by this module."""
  pass
class SequencingError(Error):
  """The exception thrown when functions are called out of order."""
  """
  For example, if you try to call a function altering the headers of your
  output when the headers have already been sent.
  """
  pass


_url_encre = re.compile(r"[^A-Za-z0-9_.!~*()-]") # RFC 2396 section 2.3
_url_decre = re.compile(r"%([0-9A-Fa-f]{2})")
_html_encre = re.compile("[&<>\"'+]")
# '+' is encoded because it is special in UTF-7, which the browser may select
# automatically if the content-type header does not specify the character
# encoding. This is paranoia and is not bulletproof, but it does no harm. See
# section 4 of www.microsoft.com/technet/security/topics/csoverv.asp
_html_encodes = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;",
                  "'": "&#39;", "+": "&#43;" }

def html_encode(raw):
  """Return the string parameter HTML-encoded."""
  """
  Specifically, the following characters are encoded as entities:
    & < > " ' +
  """
  return re.sub(_html_encre, lambda m: _html_encodes[m.group(0)], str(raw))

def url_encode(raw):
  """Return the string parameter URL-encoded."""
  return re.sub(_url_encre, lambda m: "%%%02X" % ord(m.group(0)), str(raw))

def url_decode(enc):
  """Return the string parameter URL-decoded (including '+' -> ' ')."""
  s = enc.replace("+", " ")
  return re.sub(_url_decre, lambda m: chr(int(m.group(1), 16)), s)


class Request:
  """All the information about a CGI-style request, including how to respond."""
  """Headers are buffered in a list before being sent. They are either sent
  on request, or when the first part of the body is sent. If requested, the
  body output can be buffered as well."""

  def __init__(self, handler_type):
    """Create a Request object which uses handler_type as its handler."""
    """An object of type handler_type, which should be a subclass of
    Handler, will be used to handle requests."""
    self._handler_type = handler_type
    self._doneHeaders = 0
    self._headers = []
    self._bufferOutput = 0
    self._output = StringIO.StringIO()
    self.params = {}
    """The CGI form variables passed from the client."""
    self.cookies = Cookie.SimpleCookie()
    """The HTTP cookies passed from the client."""
    self.aborted = 0
    """True if this request has been aborted (i.e. the client has gone.)"""
    self.environ = {}
    """The environment variables associated with this request."""
    self.set_header("Content-Type", "text/html; charset=iso-8859-1")

  def output_headers(self):
    """Output the list of headers."""
    if self._doneHeaders:
      raise SequencingError, "output_headers() called twice"
    for pair in self._headers:
      self._write("%s: %s\r\n" % pair)
    self._write("\r\n")
    self._doneHeaders = 1

  def clear_headers(self):
    """Clear the list of headers."""
    if self._doneHeaders:
      raise SequencingError, "cannot clear_headers() after output_headers()"
    self._headers = []

  def add_header(self, hdr, val):
    """Add a header to the list of headers."""
    if self._doneHeaders:
      raise SequencingError, \
        "cannot add_header(%s) after output_headers()" % `hdr`
    self._headers.append((hdr, val))

  def set_header(self, hdr, val):
    """Add a header to the list of headers, replacing any existing values."""
    if self._doneHeaders:
      raise SequencingError, \
        "cannot set_header(%s) after output_headers()" % `hdr`
    self.del_header(hdr)
    self._headers.append((hdr, val))

  def del_header(self, hdr):
    """Removes all values for a header from the list of headers."""
    if self._doneHeaders:
      raise SequencingError, \
        "cannot del_header(%s) after output_headers()" % `hdr`
    while 1:
      for s in self._headers:
        if s[0] == hdr:
          self._headers.remove(s)
          break
      else:
        break

  def set_buffering(self, f):
    """Specifies whether or not body output is buffered."""
    if self._output.tell() > 0 and not f:
      self.flush()
    self._bufferOutput = f

  def flush(self):
    """Flushes the body output."""
    if not self._doneHeaders:
      self.output_headers()
    self._write(self._output.getvalue())
    self._output.seek(0, 0)
    self._output.truncate()
    self._flush()

  def clear_output(self):
    """Discards the contents of the body output buffer."""
    if not self._bufferOutput:
      raise SequencingError, "cannot clear output when not buffering"
    self._output.seek(0, 0)
    self._output.truncate()

  def error(self, s):
    """Records an error message from the program."""
    """The output is logged or otherwise stored on the server. It does not
    go to the client.
    
    Must be overridden by the sub-class."""
    raise NotImplementedError, "error must be overridden"

  def _write(self, s):
    """Sends some data to the client."""
    """Must be overridden by the sub-class."""
    raise NotImplementedError, "_write must be overridden"

  def _flush(self):
    """Flushes data to the client."""
    """Must be overridden by the sub-class."""
    raise NotImplementedError, "_flush must be overridden"

  def write(self, s):
    """Sends some data to the client."""
    if self._bufferOutput:
      self._output.write(str(s))
    else:
      if not self._doneHeaders:
        self.output_headers()
      self._write(s)

  def _mergevars(self, encoded):
    """Parse variable-value pairs from a URL-encoded string."""
    """Extract the variable-value pairs from the URL-encoded input string and
    merge them into the output dictionary. Variable-value pairs are separated
    from each other by the '&' character. Missing values are allowed.

    If the variable name ends with a '*' character, then the value that is
    placed in the dictionary will be a list. This is useful for multiple-value
    fields."""
    for pair in encoded.split("&"):
      if pair == "":
        continue
      nameval = pair.split("=", 1)
      name = url_decode(nameval[0])
      if len(nameval) > 1:
        val = url_decode(nameval[1])
      else:
        val = None
      if name.endswith("!") or name.endswith("!*"):
        continue
      if name.endswith("*"):
        if self.params.has_key(name):
          self.params[name].append(val)
        else:
          self.params[name] = [val]
      else:
        self.params[name] = val

  def _mergemime(self, contenttype, encoded):
    """Parses variable-value pairs from a MIME-encoded input stream."""
    """Extract the variable-value pairs from the MIME-encoded input file and
    merge them into the output dictionary.

    If the variable name ends with a '*' character, then the value that is
    placed in the dictionary will be a list. This is useful for multiple-value
    fields. If the variable name ends with a '!' character (before the '*' if
    present) then the value will be a mime.Entity object."""
    import mime
    headers = "Content-Type: %s\n" % contenttype
    for entity in mime.Entity(encoded.read(), mime=1, headers=headers).entities:
      if not entity.content_disposition:
        continue
      if entity.content_disposition[0] != 'form-data':
        continue
      name = entity.content_disposition[1].get("name")
      if name[-1:] == "*":
        if self.params.has_key(name):
          if name[-2:-1] == "!":
            self.params[name].append(entity)
          else:
            self.params[name].append(entity.body)
        else:
          if name[-2:-1] == "!":
            self.params[name] = [entity]
          else:
            self.params[name] = [entity.body]
      elif name[-1:] == "!":
        self.params[name] = entity
      else:
        self.params[name] = entity.body

  def _read_cgi_data(self, environ, inf):
    """Read input data from the client and set up the object attributes."""
    if environ.has_key("QUERY_STRING"):
      self._mergevars(environ["QUERY_STRING"])
    if environ.get("REQUEST_METHOD") == "POST":
      if environ.get("CONTENT_TYPE", "").startswith("multipart/form-data"):
        self._mergemime(environ["CONTENT_TYPE"], inf)
      else:
        self._mergevars(inf.read(int(environ.get("CONTENT_LENGTH", "-1"))))
    if environ.has_key("HTTP_COOKIE"):
      self.cookies.load(environ["HTTP_COOKIE"])

  def traceback(self):
    """Output an exception traceback to the client, and to the local log."""
    import traceback
    exc = sys.exc_info()
    try:
      self.clear_headers()
      self.clear_output()
      self.set_header("Content-Type", "text/html; charset=iso-8859-1")
    except SequencingError:
      pass
    self.write("<html><head><title>wt traceback</title></head><body>"
      "<h1>wt traceback</h1><pre><b>")
    for line in traceback.format_exception_only(exc[0], exc[1]):
      self.write(html_encode(line))
      self.error(line)
    self.write("</b>\n")
    lines = traceback.format_tb(exc[2])
    lines.reverse()
    for line in lines:
      self.write(html_encode(line))
      self.error(line)
    self.write("</pre></body></html>\n")


class CGIRequest(Request):
  """An implementation of Request which uses the standard CGI interface."""

  def __init__(self, handler_type):
    Request.__init__(self, handler_type)
    self.__out = sys.stdout
    self.__err = sys.stderr
    self.environ = os.environ

  def process(self):
    """Read the CGI input and create and run a handler to handle the request."""
    self._read_cgi_data(self.environ, sys.stdin)
    try:
      self._handler_type().process(self)
    except:
      self.traceback()
    self.flush()

  def error(self, s):
    self.__err.write(s)

  def _write(self, s):
    if not self.aborted:
      try:
        self.__out.write(s)
      except IOError, x:
        # Ignore EPIPE, caused by the browser having gone away
        if x[0] != errno.EPIPE:
          raise
        self.aborted = 1

  def _flush(self):
    if not self.aborted:
      try:
        self.__out.flush()
      except IOError, x:
        # Ignore EPIPE, caused by the browser having gone away
        if x[0] != errno.EPIPE:
          raise
        self.aborted = 1


class Handler:
  """Handle a request."""
  def process(self, req):
    """Handle a request. req is a Request object."""
    raise NotImplementedError, "handler process function must be overridden"
