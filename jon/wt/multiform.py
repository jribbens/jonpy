# $Id$

import os.path
import jon.wt as wt
import jon.cgi as cgi


class MultiForm(wt.TemplateCode):
  name = None
  stages = 0
  filename = "mf%d.html"
  
  def init(self):
    pass

  def delete(self):
    if self.name:
      key = "multiform_%s" % self.name
    else:
      key = "multiform"
    if self.wt.session.has_key(key):
      del self.wt.session[key]

  def main(self, template):
    if self.name:
      key = "multiform_%s" % self.name
    else:
      key = "multiform"
    self.container = self.wt.session.get(key)
    if self.container is None:
      self.container = {}
      self.wt.session[key] = self.container
    if self.name:
      self.stage = self.req.params.get("multiform_stage_%s" % self.name, "")
    else:
      self.stage = self.req.params.get("multiform_stage", "")
    try:
      self.stage = int(self.stage)
    except ValueError:
      self.stage = 0
      self.container.clear()
      self.init()

    stage_objs = []
    for i in range(self.stages):
      stage_objs.append(getattr(self, "stage%d" % i)(self))
      stage_objs[i].container = self.container
      stage_objs[i].errors = []
      for key in stage_objs[i].keys:
        if key.endswith("!*"):
          ckey = key[:-2]
        elif key.endswith("!") or key.endswith("*"):
          ckey = key[:-1]
        else:
          ckey = key
        if self.req.params.has_key(key):
          value = None
          if key.endswith("!"):
            if self.req.params[key].body:
              value = self.req.params[key].body
          else:
            value = self.req.params[key]
          if value is not None:
            if hasattr(stage_objs[i], "update_%s" % ckey):
              getattr(stage_objs[i], "update_%s" % ckey)(value)
            else:
              self.container[ckey] = value
        if not hasattr(stage_objs[i], ckey):
          setattr(stage_objs[i], ckey, self.container.get(ckey, ""))

    self.errors = []
    for i in range(self.stage):
      stage_objs[i].update()
      stage_objs[i].check()
      if stage_objs[i].errors:
        self.errors += stage_objs[i].errors
        if self.stage > i:
          self.stage = i

    template = os.path.dirname(self.wt.template) + "/" + self.filename \
      % self.stage
    obj = stage_objs[self.stage]
    if obj.template_as_file:
      obj.main(open(template))
    else:
      obj.main(open(template).read())


class Stage(wt.TemplateCode):
  keys = ()

  def form(self):
    if self.outer.name:
      name = "multiform_stage_%s" % self.outer.name
    else:
      name = "multiform_stage"
    return '<input type="hidden" name="%s" value="%d">' % \
      (cgi.html_encode(name), self.outer.stage + 1)

  def update(self):
    pass

  def check(self):
    return None

  class header(wt.TemplateCode):
    class errors(wt.TemplateCode):
      class error(wt.TemplateCode):
        def main(self, template):
          for self.error in self.outer.outer.outer.outer.errors:
            self.process(template)
    class noerrors(wt.TemplateCode):
      pass

    def main(self, template):
      if self.outer.outer.errors:
        self.process(template, "errors")
      else:
        self.process(template, "noerrors")
