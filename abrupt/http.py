import os
import copy
import zlib
import gzip
import httplib
import urlparse
import tempfile
import webbrowser
import subprocess
import datetime
import Cookie
from collections import defaultdict 
from StringIO import StringIO

import abrupt.conf
from abrupt.color import *
from abrupt.utils import *

class HTTPConnection(httplib.HTTPConnection):

  def _clear(self):
    self.__state = httplib._CS_IDLE

class HTTPSConnection(httplib.HTTPSConnection):
  
  def _clear(self):
    self.__state = httplib._CS_IDLE

class Request():

  def __init__(self, fd, hostname=None, port=80, use_ssl=False):
    """Create a request. fd should be either a socket descriptor
       or a string. In both case, it should contain a full request.
       To generate a request from a URL, see c()"""
    if isinstance(fd, basestring): fd = StringIO(fd)
    try:
      self.method, url, self.http_version = read_banner(fd) 
    except:
      raise httplib.NotConnected()
    if self.method == "CONNECT":
      self.hostname, self.port = url.split(":", 1)
    else:
      p_url = urlparse.urlparse(url)
      self.url = urlparse.urlunparse(("","") + p_url[2:])
      self.hostname = p_url.hostname or hostname
      if not self.hostname: raise Exception("No hostname")
      if p_url.scheme == 'https':
        self.use_ssl = True
        self.port = int(p_url.port) if p_url.port else 443
      else:
        self.port = int(p_url.port) if p_url.port else port
        self.use_ssl = use_ssl
      self.set_headers(read_headers(fd))
      self.content = read_content(fd, self.headers, method=self.method)
      self.response = None
      
  @property
  def path(self):
    return urlparse.urlparse(self.url).path

  @property
  def query(self):
    return urlparse.urlparse(self.url).query

  @property
  def cookies(self):
    b = Cookie.SimpleCookie()
    for h, v in self.headers:
      if h == "Cookie":
        b.load(v)
    return b
  
  def set_headers(self, headers):
    self.headers = []
    for l in headers.splitlines():
      if l:
        t, v = [q.strip() for q in l.split(":", 1)]
        self.headers.append((t.title(), v))

  def _update_content_length(self):
    l = str(len(self.content)) if self.content else "0"
    for i, c in enumerate(self.headers):
      h, v = c  
      if h.title() == "Content-Length":
        self.headers[i] = (h, l) 
        break
    else:
      self.headers.append(("Content-Length", l))

  def __repr__(self):
    fields =[info(self.method), self.hostname, self.path]
    if self.use_ssl: fields.append(warning("SSL"))
    return "<" + " ".join(fields) + ">"
  
  def copy(self):
    r_new = copy.copy(self)
    r_new.headers = copy.deepcopy(self.headers)
    r_new.response = None
    return r_new

  def __str__(self):
    s = StringIO()
    s.write("%s %s %s\r\n" % (self.method, self.url, self.http_version))
    for h, v in self.headers:
      s.write("%s: %s\r\n" % (h, v))
    s.write("\r\n")
    if self.content:
      s.write(self.content)
    return s.getvalue()

  def __eq__(self, r):
    if self.hostname != r.hostname or \
       self.port != r.port or \
       self.use_ssl != r.use_ssl or \
       self.url != r.url or \
       self.headers != r.headers:
      return False
    if (self.content or r.content) and self.content != r.content:
      return False 
    return True
      
  def __call__(self, conn=None):
    if not conn:
      if self.use_ssl:
        conn = httplib.HTTPSConnection(self.hostname + ":" + str(self.port))
      else:
        conn = httplib.HTTPConnection(self.hostname + ":" + str(self.port))
    conn.request(self.method, self.url, self.content, dict(self.headers))
    n1 = datetime.datetime.now() 
    self.response = Response(conn.sock.makefile('rb',0), self)
    n2 = datetime.datetime.now()
    self.response.time = n2 - n1

  def edit(self):
    fd, fname = tempfile.mkstemp()
    with os.fdopen(fd, 'w') as f:
      f.write(str(self))
    editor = os.environ['EDITOR'] if 'EDITOR' in os.environ else "/usr/bin/vim"
    ret = subprocess.call(editor + " " + fname, shell=True)
    f = open(fname, 'r')
    r_new = Request(f, self.hostname, self.port, self.use_ssl)
    return r_new

  def play(self, options='-o2 -c "set autoread" -c "autocmd CursorMoved * checktime" -c "autocmd CursorHold * checktime"'):
    editor = os.environ['EDITOR'] if 'EDITOR' in os.environ else "/usr/bin/vim"
    fdreq, freqname = tempfile.mkstemp()
    fdrep, frepname = tempfile.mkstemp()
    with os.fdopen(fdreq, 'w') as f:
      f.write(str(self))
    if self.response:
      with os.fdopen(fdrep, 'w') as f:
        f.write(str(self.response))
    ret = subprocess.Popen(editor + " " + freqname + " " + frepname + " " + options, shell=True, )
    last_access = os.stat(freqname).st_mtime
    r_new = None
    while ret.poll() != 0:
      if os.stat(freqname).st_mtime != last_access:
        freq = open(freqname, 'r')
        try:  
          r_new = Request(freq, self.hostname, self.port, self.use_ssl)
          freq.close()
          r_new()
          if r_new.response:
            frep = open(frepname, 'w')
            frep.write(str(r_new.response))
        except Exception, e:
          frep = open(frepname, 'w')
          frep.write("Error:\n")
          frep.write(str(e))
        frep.close()
        last_access = os.stat(freqname).st_mtime
    return r_new

  def extract(self, arg):
    if arg.startswith("response__"):
      if self.response: 
        return self.response.extract(arg.replace("response__", ""))
    if hasattr(self, arg):
      return getattr(self, arg)
    if self.query:
      query = urlparse.parse_qs(self.query, True)
      print query
      if arg in query:
        return query[arg][0]
    if self.content:
      post = urlparse.parse_qs(self.content, True)
      print post
      if arg in post:
        return post[arg][0]
    c = self.cookies
    if c:
      if arg in c:
        return c[arg].value      
  
  def filter(self, **kwds):
    check_response = {}
    for kw in kwds:
      if kw.startswith("response__"):
        check_response[kw.replace("response__", "")] = kwds[kw]
      if hasattr(self, kw):
        if getattr(self, kw) != kwds[kw]:
          return False
    if check_response:
      if not self.response or not self.response.filter(**check_response): 
        return False
    return True

  def i(self, **kwds):
    from abrupt.injection import inject
    return inject(self, **kwds)
  
  def i_at(self, offset, payload, **kwds):
    from abrupt.injection import inject_at
    return inject_at(self, offset, payload, **kwds)

  def follow(self):
    if not self.response or not self.response.status in ('301', '302'):
      return
    else:
      for h, v in self.response.headers:
        if h == "Location":
          url_p = urlparse.urlparse(v)
          if url_p.scheme in ('http', 'https'):
            return c(v)
          elif not url_p.scheme and url_p.path:
            nr = self.copy()
            n_path = urlparse.urljoin(self.url, v)
            nr.url = urlparse.urlunparse(urlparse.urlparse(self.url)[:2] + urlparse.urlparse(n_path)[2:])
            return nr
          else:
            raise Exception("Unknown redirection, please add some code in abrupt/http.py:186")  

def create(url):
  """Create a request on the fly, based on a URL"""
  p_url = urlparse.urlparse(url) 
  host = p_url.hostname
  if not p_url.path:
    url += "/"
  return Request("""GET %s HTTP/1.1
Host: %s
User-Agent: Mozilla/5.0 (Windows; U; MSIE 9.0; Windows NT 0.9; en-US)
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8
Accept-Language: en;q=0.5,fr;q=0.2
Accept-Encoding: gzip, deflate 
Accept-Charset: ISO-8859-1,utf-8;q=0.7,*;q=0.7

""" % (url,host))

c = create

class Response():
  
  def __init__(self, fd, request):
    self.http_version, self.status, self.reason = read_banner(fd)
    self.set_headers(read_headers(fd))
    if request.method == "HEAD": 
      self.content = ""
    else:
      self.content = read_content(fd, self.headers, self.status)
      if self.content:
        self.readable_content = _clear_content(self.headers, self.content)
      else:
        self.readable_content = ""

  def __repr__(self):
    flags = []
    if ("Transfer-Encoding", "Chunked") in self.headers: flags.append("Chunked")
    if ("Content-Encoding", "gzip") in self.headers: flags.append("Gzip")
    if ("Content-Encoding", "deflate") in self.headers: flags.append("Zip")
    if self.content: flags.append(str(len(self.content)))
    return "<" + color_status(self.status) + " " + " ".join(flags)  + ">"

  def __str__(self):
    s = StringIO()
    s.write("%s %s %s\r\n" % (self.http_version, self.status, self.reason))
    for h, v in self.headers:
      s.write("%s: %s\r\n" % (h, v))
    s.write("\r\n")
    if self.content:
      s.write(self.readable_content)
    return s.getvalue()

  def view(self):
    fd, fname = tempfile.mkstemp()
    with os.fdopen(fd, 'w') as f:
      f.write(str(self))
    editor = os.environ['EDITOR'] if 'EDITOR' in os.environ else "/usr/bin/vim"
    ret = subprocess.call(editor + " " + fname, shell=True)

  @property
  def cookies(self):
    b = Cookie.SimpleCookie()
    for h, v in self.headers:
      if h == "Set-Cookie":
        b.load(v)
    return b

  @property
  def closed(self):
    if ("Connection", "close") in self.headers or self.http_version == "HTTP/1.0":
      return True
    return False

  @property
  def length(self):
    return len(self.readable_content)

  @property
  def content_type(self):
    for h,v in self.headers:
      if h == "Content-Type":
        return v

  def raw(self):
    s = StringIO()
    s.write("%s %s %s\r\n" % (self.http_version, self.status, self.reason))
    for h, v in self.headers:
      s.write("%s: %s\r\n" % (h, v))
    s.write("\r\n")
    if self.content:
      s.write(self.content)
    return s.getvalue()
    
  def set_headers(self, headers):
    self.headers = [] 
    for l in headers.splitlines():
      if l:
        t, v = [q.strip() for q in l.split(":", 1)]
        self.headers.append((t.title(), v))

  def preview(self):
    fd, fname = tempfile.mkstemp()
    with os.fdopen(fd, 'w') as f:
      f.write(self.readable_content)
    webbrowser.open_new_tab(fname)
    #os.unlink(fname)

  def extract(self, arg):
    if hasattr(self, arg):
      return getattr(self, arg)
    c = self.cookies
    if arg in c:
      return c[arg].value
  
  def filter(self, **kwds):
    for kw in kwds:
      if not hasattr(self, kw): 
        return False
      if getattr(self, kw) != kwds[kw]:
        return False
    return True
  
class RequestSet():
  
  def __init__(self, reqs=None):
    self.reqs = reqs if reqs else []
    self.hostname = None
  
  def __call__(self):
    self.run()

  def __getitem__(self, i):
    return self.reqs[i]

  def __len__(self):
    return len(self.reqs)

  def __add__(self, other):
    return RequestSet(self.reqs + other.reqs)

  def __bool__(self):
    return bool(self.reqs)

  def pop(self):
    return self.reqs.pop()  

  def filter(self, **kwds):
    return RequestSet([ r for r in self.reqs if r.filter(**kwds)])

  def extract(self, arg):
    return [ r.extract(arg) for r in self.reqs]

  def __repr__(self):
    status = defaultdict(int)
    for r in self.reqs:
      if r.response:
        status[r.response.status] += 1
      else:
        status["unknown"] += 1
    status_flat = [ color_status(x) + ":" + str(nb) for x, nb in status.items()]
    hostnames = set([r.hostname for r in self.reqs])
    return "{" + " ".join(status_flat) + " | " + ", ".join(hostnames) + "}"
     
  def __str__(self):
    columns =  ([
      ("Method", lambda r, i: info(r.method)),
      ("Path", lambda r, i:  r.path[:27] + "..." if len(r.path)>30 else r.path),
      ("Query", lambda r,i: r.query[:27] + "..." if len(r.query)>30 else r.query),
      ("Status", lambda r, i: color_status(r.response.status)
                 if r.response else "-"),
      ("Length", lambda r, i: str(len(r.response.content)) 
                 if (r.response and r.response.content) else "-")
      ])
    if any([hasattr(x, "payload") for x in self.reqs]):
      columns.insert(2, ("Payload", lambda r, i: getattr(r,"payload","-")[:30]))
      columns.append(("Time", lambda r,i: "%.4f" % (r.response.time.total_seconds()) 
                              if r.response else "-"))
    if len(set([r.hostname for r in self.reqs])) > 1:
      columns.insert(1, ("Host", lambda r, i: r.hostname)) 
    if len(self.reqs) > 5:
      columns.insert(0, ("Id", lambda r,i: str(i)))
    return make_table(self.reqs, columns)

  def _init_connection(self):
    if self.use_ssl:
      conn = HTTPSConnection(self.hostname + ":" + str(self.port))
    else:
      conn = HTTPConnection(self.hostname + ":" + str(self.port))
    return conn

  def run(self, verbose=False):
    if not self.reqs:
      raise Exception("No request to proceed")
    hostnames = set([r.hostname for r in self.reqs])
    ports = set([r.port for r in self.reqs])
    use_ssls = set([r.use_ssl for r in self.reqs])
    if len(hostnames) > 1 or len(ports) > 1 or len(use_ssls) > 1:
      raise Exception("Only one host per request set to run them")
    self.hostname = hostnames.pop()
    self.port = ports.pop()
    self.use_ssl = use_ssls.pop()
    conn = self._init_connection()
    print "Running %s requests..." % len(self.reqs),
    clear_line()
    for i, r in enumerate(self.reqs):
      if not verbose:
        print "Running %s requests...%d%%" % (len(self.reqs), i*100/len(self.reqs)),
        clear_line()
      next = False
      if r.response: next = True
      while not next:
        try:
          if verbose: print repr(r)
          r(conn=conn)
          conn._clear()
          if verbose: print repr(r.response)
          if r.response.closed: 
            conn = self._init_connection()
          next = True
        except httplib.HTTPException:
          conn = self._init_connection()
          next = False
    print "Running %s requests...done." % len(self.reqs)
    conn.close()


# Following, internal function used by Request and Response
# mostly inspired by httplib

def read_banner(fp):
  return re_space.split(fp.readline().strip(), maxsplit=2)

def read_headers(fp):
  headers = ""
  while True:
    l = fp.readline()
    headers += l
    if l == "\r\n" or l == "\n":
      break
  return headers

def read_content(fp, headers, status=None, method=None):
  if status == "304": 
    return None
  elif ("Transfer-Encoding", "chunked") in headers:
    return _chunked_read_content(fp).getvalue()
  elif "Content-Length" in zip(*headers)[0]:
    length_str = zip(*headers)[1][zip(*headers)[0].index("Content-Length")]
    length = int(length_str)
    return _read_content(fp, length).getvalue()
  elif status == "200" or method =="POST": # No indication on what we should read, so just read
    return fp.read()
  return None

def _chunked_read_content(fp):
  buffer = StringIO()
  while True:
    l = fp.readline()
    buffer.write(l)
    s = int(l,16)
    if s == 0:
      buffer.write(fp.readline())
      return buffer
    buffer.write(_read_content(fp, s).getvalue())
    buffer.write(fp.readline()) 

def _read_content(fp, length):
  buffer = StringIO()
  while True:
    l = len(buffer.getvalue())
    if l < length:
      buffer.write(fp.read(length-l))
    else:
      break
  return buffer

def _clear_content(headers, content):
  if ("Transfer-Encoding", "chunked") in headers:
    content_io = StringIO(content)
    buffer = StringIO()
    while True:
      s = int(content_io.readline(), 16)
      if s == 0: 
        readable_content = buffer.getvalue()
        break
      buffer.write(_read_content(content_io, s).getvalue())
      content_io.readline()
  else:
    readable_content = content
  if ("Content-Encoding", "gzip") in headers:
    cs = StringIO(readable_content)
    gzipper = gzip.GzipFile(fileobj=cs)
    return gzipper.read()
  if ("Content-Encoding", "deflate") in headers:
    unzipped = StringIO(zlib.decompress(readable_content, -zlib.MAX_WBITS))
    return unzipped.read()
  return readable_content
