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


__UNDEF__ = []

def _lookup(name, frame, locls):
  if name in locls:
    return "local", locls[name]
  if name in frame.f_globals:
    return "global", frame.f_globals[name]
  if "__builtins__" in frame.f_globals and \
    hasattr(frame.f_globals["__builtins__"], name):
    return "builtin", getattr(frame.f_globals["__builtins__"], name)
  return None, __UNDEF__


def _scanvars(reader, frame, locls):
  import tokenize, keyword
  vrs = []
  lasttoken = None
  parent = None
  prefix = ""
  for ttype, token, start, end, line in tokenize.generate_tokens(reader):
    if ttype == tokenize.NEWLINE:
      break
    elif ttype == tokenize.NAME and token not in keyword.kwlist:
      if lasttoken == ".":
        if parent is not __UNDEF__:
          value = getattr(parent, token, __UNDEF__)
          vrs.append((prefix + token, prefix, value))
      else:
        (where, value) = _lookup(token, frame, locls)
        vrs.append((token, where, value))
    elif token == ".":
      prefix += lasttoken + "."
      parent = value
    else:
      parent = None
      prefix = ""
    lasttoken = token
  return vrs


def _tb_encode(s):
  return html_encode(s).replace(" ", "&nbsp;")


def traceback(req, html=0):
  import traceback, time, types, linecache, inspect, repr
  repr = repr.Repr()
  repr.maxother = 80
  repr.maxstring = 80
  repr = repr.repr
  (etype, evalue, etb) = sys.exc_info()
  if type(etype) is types.ClassType:
    etype = etype.__name__
  if html:
    try:
      req.clear_headers()
      req.clear_output()
      req.set_header("Content-Type", "text/html; charset=iso-8859-1")
    except SequencingError:
      req.write("</font></font></font></script></object></blockquote></pre>"
        "</table></table></table></table></table></table></font></font>")
    req.write("""\
<?xml version="1.0" encoding="iso-8859-1"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>jonpy traceback: %s</title>
<style type="text/css"><!--
BODY { background-color: #f0f0f8; font-family: helveta, arial, sans-serif }
.tb_head { background-color: #6622aa; color: #ffffff }
.tb_title { font-size: x-large }
.tb_frame { background-color: #d8bbff }
.tb_lineno { font-size: smaller }
.tb_codehigh { background-color: #ffccee }
.tb_code { color: #909090 }
.tb_dump { color: #909090; font-size: smaller }
--></style>
</head><body>
<table width="100%%" cellspacing="0" cellpadding="0" border="0">
<tr class="tb_head">
<td valign="bottom" class="tb_title">&nbsp;<br /><strong>%s</strong></td>
<td align="right" valign="bottom">%s<br />%s</td></tr></table>
<p>A problem occurred in a Python script. Here is the sequence of
function calls leading up to the error, with the most recent first.</p>
""" % (_tb_encode(etype), _tb_encode(etype),
      "Python %s: %s" % (sys.version.split()[0], sys.executable),
      time.ctime(time.time())))
  req.error("jonpy error: %s at %s\n" % (etype, time.ctime(time.time())))
  # this code adapted from the standard cgitb module
  # unfortunately we cannot use that module directly,
  # mainly because it won't allow us to output to the log
  if html:
    req.write("<p><strong>%s</strong>: %s" % (_tb_encode(etype),
      _tb_encode(evalue)))
  req.error("%s: %s\n" % (etype, evalue))
  #if type(evalue) is types.InstanceType:
  #  for name in dir(evalue):
  #    if html:
  #      req.write("\n<br /><tt>&nbsp;&nbsp;&nbsp;&nbsp;</tt>%s&nbsp;= %s" %
  #        (_tb_encode(name), _tb_encode(repr(getattr(evalue, name)))))
  #    req.error("  %s = %s\n" % (name, repr(getattr(evalue, name))))
  if html:
    req.write("</p>\n")
  frames = []
  records = inspect.getinnerframes(etb, 7)
  records.reverse()
  for frame, fn, lnum, func, lines, index in records:
    if html:
      req.write("""\
<table width="100%" cellspacing="0" cellpadding="0" border="0">""")
    fn = fn and os.path.abspath(fn) or "?"
    args, varargs, varkw, locls = inspect.getargvalues(frame)
    if func != "?":
      fav = inspect.formatargvalues(args, varargs, varkw, locls)
      if html:
        req.write("<tr><td class=\"tb_frame\">%s in <strong>%s</strong>%s</td>"
          "</tr>\n" % (_tb_encode(fn), _tb_encode(func), _tb_encode(fav)))
      req.error("%s in %s%s\n" % (fn, func, fav))
    else:
      if html:
        req.write("<tr><td class=\"tb_head\">%s</td></tr>\n" %
          (_tb_encode(fn),))
      req.error("%s\n" % (fn,))
    highlight = {}
    def reader(lnum=[lnum]):
      highlight[lnum[0]] = 1
      try:
        return linecache.getline(fn, lnum[0])
      finally:
        lnum[0] += 1
    vrs = _scanvars(reader, frame, locls)
    if index is not None:
      i = lnum - index
      for line in lines:
        if html:
          if i in highlight:
            style = "tb_codehigh"
          else:
            style = "tb_code"
          req.write("<tr><td class=\"%s\"><code><span class=\"tb_lineno\">"
            "%s</span>&nbsp;%s</code></td></tr>\n" %
            (style, "&nbsp;" * (5 - len(str(i))) + str(i), _tb_encode(line)))
        req.error("%s %s" % (" " * (5-len(str(i))) + str(i), line))
        i += 1
    done = {}
    dump = []
    htdump = []
    for name, where, value in vrs:
      if name in done:
        continue
      done[name] = 1
      if value is not __UNDEF__:
        if where == "global":
          dump.append("global %s = %s" % (name, repr(value)))
          htdump.append("<em>global</em> <strong>%s</strong>&nbsp;= %s" %
            (_tb_encode(name), _tb_encode(repr(value))))
        elif where == "builtin":
          dump.append("builtin %s = %s" % (name, repr(value)))
          htdump.append("<em>builtin</em> <strong>%s</strong>&nbsp;= %s" %
            (_tb_encode(name), _tb_encode(repr(value))))
        elif where == "local":
          dump.append("%s = %s" % (name, repr(value)))
          htdump.append("<strong>%s</strong>&nbsp;= %s" %
            (_tb_encode(name), _tb_encode(repr(value))))
        else:
          dump.append("%s%s = %s" % (where, name.split(".")[-1], repr(value)))
          htdump.append("%s<strong>%s</strong>&nbsp;= %s" %
            (_tb_encode(where), _tb_encode(name.split(".")[-1]),
            _tb_encode(repr(value))))
      else:
        dump.append("%s undefined" % (name,))
        htdump.append("%s <em>undefined</em>" % (_tb_encode(name,)))
    if html:
      req.write("<tr><td class=\"tb_dump\">%s</td></tr>\n" %
        (", ".join(htdump),))
    req.error(", ".join(dump) + "\n")
    if html:
      req.write("</table>\n")
  if html:
    req.write("</body></html>\n")
  linecache.clearcache()


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

  def _init(self):
    self._doneHeaders = 0
    self._headers = []
    self._bufferOutput = 1
    self._output = StringIO.StringIO()
    try:
      del self.params
    except AttributeError:
      pass
    self.cookies = Cookie.SimpleCookie()
    if self.environ.has_key("HTTP_COOKIE"):
      self.cookies.load(self.environ["HTTP_COOKIE"])
    self.aborted = 0
    self.set_header("Content-Type", "text/html; charset=iso-8859-1")

  def __getattr__(self, name):
    if name == "params":
      self.params = {}
      self._read_cgi_data(self.environ, self.stdin)
      return self.__dict__["params"]
    raise AttributeError, "%s instance has no attribute %s" % \
      (self.__class__.__name__, `name`)

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

  def traceback(self):
    traceback(self)
    try:
      self.clear_headers()
      self.clear_output()
      self.set_header("Content-Type", "text/html; charset=iso-8859-1")
    except SequencingError:
      pass
    self.write("""\
<html><head><title>Error</title></head>
<body><h1>Error</h1>
<p>Sorry, an error occurred. Please try again later.</p>
</body></html>""")


class CGIRequest(Request):
  """An implementation of Request which uses the standard CGI interface."""

  def __init__(self, handler_type):
    Request.__init__(self, handler_type)

  def _init(self):
    self.__out = sys.stdout
    self.__err = sys.stderr
    self.environ = os.environ
    self.stdin = sys.stdin
    Request._init(self)

  def process(self):
    """Read the CGI input and create and run a handler to handle the request."""
    self._init()
    try:
      handler = self._handler_type()
    except:
      self.traceback()
    else:
      try:
        handler.process(self)
      except:
        handler.traceback(self)
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

  def traceback(self, req):
    """Display a traceback, req is a Request object."""
    req.traceback()


class DebugHandlerMixIn:
  def traceback(self, req):
    """Display a traceback, req is a Request object."""
    traceback(req, html=1)


class DebugHandler(DebugHandlerMixIn, Handler):
  pass
