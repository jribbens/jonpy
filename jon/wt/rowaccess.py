# $Id$

import jon.wt as wt

class RowAccess(wt.TemplateCode):
  rowaccess_attrib = "row"

  def __getattr__(self, name):
    try:
      return getattr(self, self.rowaccess_attrib)[name]
    except KeyError:
      raise AttributeError, name
