# $Id$

import re
import jon.wt as wt
import jon.cgi as cgi

class textblock(wt.TemplateCode):
  def text(self):
    return ""

  def main(self, template):
    for self.paragraph in re.split(r"\r?\n\r?\n", self.text()):
      self.paragraph = cgi.html_encode(self.paragraph)
      self.paragraph = self.paragraph.replace("\n", "<br>")
      self.process(template)


class textblock_links(wt.TemplateCode):
  def text(self):
    return ""

  def main(self, template):
    for self.paragraph in re.split(r"\r?\n\r?\n", self.text()):
      self.paragraph = cgi.html_encode(self.paragraph)
      self.paragraph = self.paragraph.replace("\n", "<br>")
      def repl(m):
        return '<a target="_blank" href="%s">%s</a>' % \
          (m.group(2), m.group(1))
      self.paragraph = re.sub(r"\|([^|]+)\|([^|]+)\|", repl, self.paragraph)
      self.process(template)
