# $Id$

import os.path
import jon.wt as wt
import jon.cgi as cgi


class MultiForm(wt.TemplateCode):
  name = "standard"
  stages = 0
  filename = "mf%d.html"
  
  def init(self):
    pass

  def _get_name(self):
    if self.name:
      return "multiform_%s" % self.name
    return None

  def delete(self):
    key = self._get_name()
    if key is not None and self.wt.session.has_key(key):
      del self.wt.session[key]

  def main(self, template):
    key = self._get_name()

    # Find existing container, if it's in the session

    if key is not None:
      self.container = self.wt.session.get(key)
      if self.container is None:
        self.container = {}
        self.wt.session[key] = self.container
    else:
      self.container = {}

    # Determine which stage we're at. Initialise if this is a new run.

    if key is None:
      self.stage = self.req.params.get("multiform_stage", "")
    else:
      self.stage = self.req.params.get("%s_stage" % key, "")
    try:
      self.stage = int(self.stage)
    except ValueError:
      self.stage = 0
      self.container.clear()
      self.init()

    # Create the stage objects. Update the container with submitted form
    # values. Update stage objects with container values.

    self.stage_objs = []
    for i in range(self.stages):
      self.stage_objs.append(getattr(self, "stage%d" % i)(self))
      self.stage_objs[i].container = self.container
      self.stage_objs[i].errors = []
      for key in self.stage_objs[i].keys:
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
            if hasattr(self.stage_objs[i], "update_%s" % ckey):
              getattr(self.stage_objs[i], "update_%s" % ckey)(value)
            else:
              self.container[ckey] = value
        if not hasattr(self.stage_objs[i], ckey):
          setattr(self.stage_objs[i], ckey, self.container.get(ckey, ""))

    # Check for errors and adjust stage as necessary.

    self.errors = []
    for i in range(self.stage):
      self.stage_objs[i].update()
      self.stage_objs[i].check()
      if self.stage_objs[i].errors:
        self.errors += self.stage_objs[i].errors
        if self.stage > i:
          self.stage = i

    # Display appropriate stage object.

    template = os.path.dirname(self.wt.template) + "/" + self.filename \
      % self.stage
    obj = self.stage_objs[self.stage]
    if obj.template_as_file:
      obj.main(open(template, "rb"))
    else:
      obj.main(open(template, "rb").read())


class Stage(wt.TemplateCode):
  keys = ()

  def form(self):
    if self.outer.name is not None:
      return '<input type="hidden" name="multiform_%s_stage" value="%d" />' % \
        (cgi.html_encode(self.outer.name), self.outer.stage + 1)
    s = ['<input type="hidden" name="multiform_stage" value="%d" />' % \
      (self.outer.stage + 1,)]
    for stage in range(self.outer.stages):
      if stage == self.outer.stage:
        continue
      for key in self.outer.stage_objs[stage].keys:
        if self.outer.container.has_key(key):
          s.append('<input type="hidden" name="%s" value="%s" />' % \
            (cgi.html_encode(key), cgi.html_encode(self.outer.container[key])))
    return "".join(s)

  def update(self):
    pass

  def check(self):
    pass

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
