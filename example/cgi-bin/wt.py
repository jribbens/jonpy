#!/usr/local/bin/python

# $Id$

import jon.wt as wt
import jon.fcgi as fcgi


fcgi.Server({fcgi.FCGI_RESPONDER: wt.Handler}).run()
