#!/usr/bin/env python
#
# Copyright 2011 Oli McCormack. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.



"""Main Controller for Weather app."""

import os
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp import util
from google.appengine.api import memcache
from django.utils import simplejson
import models
import logging
import urllib
import re
import StringIO
import csv
import time
import random
import urllib2
import settings
import hashlib
from urlparse import urlparse
from google.appengine.api import urlfetch


class Error(Exception):
  """Base class for error"""
  def __init__(self, value):
    self.value = value

  def __str__(self):
    return repr(self.value)


class InvalidProtocolError(Error):
  """An invalid protocol is provided for a urlfetch call."""
  pass


class ContentFetchError(Error):
  """Fetching content failed."""
  pass


BASE_KEY_LEN = 15
SETTINGS = {"DEVELOPER": "oli (dev@olimcc.com)",
            "VERSION": 1,
            "APP_NAME": "WeatherDev"}


def Render(handler, tname="index.html", values=0):
  """A function to render data in templates.

  All Request Handlers send data through this function to a template page.

  Passes a dictionary to a template, which holds data that used
  on the template page. Below, this dictionary is called 'set_values'. It
  becomes populate it with some defaults: user, developer, etc as these
  are things used on every page of a site (thus, there is no
  need to perform the checks in every request handler).

  This dictionary is updated by 'values', which are passed in when the function
  is called.

  Args:
    handler: The current handler
    tname: The template name (html file) that should be used with this handler
    values: A dictionary of items that are used in this template

  Returns:
    True
  """
  temp = os.path.join(os.path.dirname(__file__),
                      "templates"+"/"+tname)
  if not os.path.isfile(temp):
    return False

  set_values = {"developer": SETTINGS["DEVELOPER"],
                "version": SETTINGS["VERSION"],
                "app_name": SETTINGS["APP_NAME"]}
  if values:
    set_values.update(values)
  outstr = template.render(temp, set_values)
  handler.response.out.write(outstr)
  return True


def ValidateCallUrl(url, check_content=False):
  """Validate URL.

  Args:
    url: (string) the url at which files are stored.
    check_content: (string) the filename of a specific file to test.

  Raises:
    InvalidProtocolError: if protocol not one of http/https.
    ContentFetchError: If content not fetchable.
  """
  url_res = urlparse(url)
  if not url_res.scheme:
    raise InvalidProtocolError('Protocol (http, https) must be included')
  if check_content:
    try:
      urllib2.urlopen(url + check_content)
    except urlfetch.DownloadError:
      raise ContentFetchError('Error retrieving testing value from url: ' +
                              url + check_content)
  return


class BaseHandler(webapp.RequestHandler):
  """Base."""

  def GetSuccess(self, data):
    """Get a success response object.

    Args:
      data: (dictionary) package to return with response.

    Returns:
      (string) json formatted result object.
    """
    return simplejson.dumps({
      'status': 'success',
      'data': data,
    })

  def GetError(self, error):
    """Get an error response object.

    Args:
      error: (string) string describing error to return with response.

    Returns:
      (string) json formatted result object.
    """
    return simplejson.dumps({
      'status': 'error',
      'description': str(error),
    })

  def GetUrlParams(self, arguments=None):
    """Obtain URL parameters sent with request."""
    vals = {}
    arguments = arguments if arguments else self.request.arguments()
    for argument in arguments:
      vals[argument] = self.request.get(argument, None)
    return vals

  def __init__(self):
    pass


class AdminHandler(BaseHandler):
  """Handler for admin functionality."""

  def GetKey(self, path):
    """Gets a key representing the site in question.

    The key will be of minimum length: BASE_KEY_LEN

    Args:
      path: (string) the url for which a key should be generated.
    Returns:
      key (string).
    """
    n = BASE_KEY_LEN
    while True:
      key = hashlib.sha224(path).hexdigest()[:n]
      if not models.Site.get_by_key_name(key):
        return key
      n += 1

  def get(self):
    """GET handler."""
    sites = models.User.current().site_set
    Render(self, '/admin.html', {'sites': sites})

  def post(self):
    """POST handler."""
    path = self.request.get('urlpath')
    try:
      ValidateCallUrl(path, 'clientraw.txt')
    except Error, err:
      self.response.out.write(self.GetError(err))
      return
    key = self.GetKey(path)
    models.Site(
      key_name = key,
      path = path,
      owner = models.User.current()).put()
    self.redirect('/admin')


class ApiHandler(BaseHandler):
  """Handler for API calls.

  Args:
    path: (string) url path at which files are stored.
    file_name: (string) file name to fetch.
    mc_time: (int) duration to store results in memcache (unused).

  Returns:
    (string) file content.
  """

  def GetData(self, path, file_name, mc_time):
    try:
      file_path = path + file_name + "?" + str(time.time())
      resource = urllib2.urlopen(file_path)
      return resource.readlines()[0].split()
    except IndexError, e:
      self.response.out.write(
        self.GetError('unable to fetch data'))
      return

  def GetResponse(self):
    """Get an API response dict.

    Returns:
      (dictionary) response dict.
    """
    return {
       'current': {},
       'lasthour': {},
       'lastday': {},
       'lastmonth': {},
       'core': {}}

  def get(self):
    """GET handler."""
    #print 'hi'
    #print self.request.remote_addr
    #requester = self.request.headers['Referer']

    mandatory_params = ['id', 'callback']
    params = self.GetUrlParams(mandatory_params)
    if None in params.values():
      self.response.out.write(
        self.GetError('id and callback parameter must be provided'))
      return

    site = models.Site.get_by_key_name(params['id'])
    if site is None:
      self.response.out.write(
        self.GetError('site does not exist'))
      return

    response = self.GetResponse()

    # fetch all current metrics from clientraw.txt
    # reflects the moment recent snapshot of data
    # settings.cr_fields describes what will be returned here
    clientraw = self.GetData(site.path, 'clientraw.txt', 5)
    for i, config in enumerate(settings.cr_fields):
      response['current'][config[0]] = {
        'value': clientraw[i],
        'unit': config[1],
      }

    # select a set of core current metrics to return, from clientraw.txt
    # settings.core describes what will be included here
    for config in settings.core:
      response['core'][config[0]] = response['current'][config[1]]

    # fetch data for the last hour from clientrawhour.txt
    # returned data is per minute, for the past 60 mins
    # settings.hourly_fields describes what will be included here
    clientrawhour = self.GetData(site.path, 'clientrawhour.txt', 3600)
    for config in settings.hourly_fields:
      response['lasthour'][config[0]] = {
        'value': clientrawhour[config[1]:config[1]+config[2]],
        'unit': settings.units[config[0]],
      }

    # fetch data for the last hour from clientrawextra.txt
    # returned data is per hour, for the past 24 hours
    # settings.daily_fields describes what will be included here
    clientrawextra = self.GetData(site.path, 'clientrawextra.txt', 3600*20)
    for config in settings.daily_fields:
      ind = range(config[1][0], config[1][0]+config[1][1]) + range(config[2][0], config[2][0]+config[2][1])
      response['lastday'][config[0]] = {
        'value': [clientrawextra[i] for i in ind],
        'unit': settings.units[config[0]]
      }

    # fetch data for the last hour from clientrawdaily.txt
    # returned data is per day, for the past 31 hours
    # settings.monthly_fields describes what will be included here
    clientrawdaily = self.GetData(site.path, 'clientrawdaily.txt', 3600*24)
    for config in settings.monthly_fields:
      response['lastmonth'][config[0]] = {
        'value': clientrawdaily[config[1]:config[1]+config[2]],
        'unit': settings.units[config[0]],
      }
    self.response.out.write(
    params['callback'] + "(" + self.GetSuccess(response) + ")")


def real_main():
  application = webapp.WSGIApplication([("/admin", AdminHandler),
                                       ("/api", ApiHandler),],
                                       debug=True)
  util.run_wsgi_app(application)


def profile_main():
  #  This is the for profiling page run time
  #  We've renamed our original main() above to real_main()
  import cProfile
  import pstats
  prof = cProfile.Profile()
  prof = prof.runctx("real_main()", globals(), locals())
  print "<pre>"
  stats = pstats.Stats(prof)
  stats.sort_stats("cumulative")
  stats.print_stats("main")
  print "</pre>"

main = real_main

if __name__ == "__main__":
  main()
