# -*- coding: utf-8 -*-
# Amara, universalsubtitles.org
#
# Copyright (C) 2012 Participatory Culture Foundation
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see
# http://www.gnu.org/licenses/agpl-3.0.html.
import datetime
import itertools
import zlib

from django.conf import settings
from django.db import models
from django.utils import simplejson as json
from django.utils.translation import ugettext_lazy as _

from apps.auth.models import CustomUser as User
from apps.videos.models import Video


ALL_LANGUAGES = [(val, _(name))for val, name in settings.ALL_LANGUAGES]


def mapcat(fn, iterable):
    """Mapcatenate.

    Map the given function over the given iterable.  Each mapping should result
    in an interable itself.  Concatenate these results.

    E.g.:

        foo = lambda i: [i, i+1]
        mapcatenate(foo, [20, 200, 2000])
        [20, 21, 200, 201, 2000, 2001]

    """
    return itertools.chain.from_iterable(itertools.imap(fn, iterable))


def subtitles_to_json(subtitles):
    return json.dumps(subtitles)

def json_to_subtitles(json_subtitles):
    return json.loads(json_subtitles)


def lineage_to_json(lineage):
    return json.dumps(lineage)

def json_to_lineage(json_lineage):
    return json.loads(json_lineage)


def get_lineage(parents):
    """Return a lineage map for a version that has the given parents."""
    lineage = {}

    for parent in parents:
        l, v = parent.language_code, parent.version_number

        if l not in lineage or lineage[l] < v:
            lineage[l] = v

        for l, v in parent.lineage.items():
            if l not in lineage or lineage[l] < v:
                lineage[l] = v

    return lineage


# Subtitle Objects ------------------------------------------------------------
class Subtitle(object):
    """A single subtitle."""

    def __init__(self, start_ms, end_ms, content, starts_paragraph=False):
        if start_ms != None and end_ms != None:
            assert start_ms <= end_ms, 'Subtitles cannot end before they start!'

        self.start_ms = start_ms
        self.end_ms = end_ms
        self.content = content
        self.starts_paragraph = starts_paragraph

    def __eq__(self, other):
        if type(self) is type(other):
            return (
                self.start_ms == other.start_ms
                and self.end_ms == other.end_ms
                and self.content == other.content
                and self.starts_paragraph == other.starts_paragraph
            )
        else:
            return False

    def __unicode__(self):
        return u"Subtitle (%s to %s): '%s'" % (self.start_ms, self.end_ms,
                                               self.content)
    def __str__(self):
        return unicode(self).encode('utf-8')


    # Serialization
    def to_dict(self):
        meta = {}

        if self.starts_paragraph:
            meta['starts_paragraph'] = True

        return {
            'start_ms': self.start_ms,
            'end_ms': self.end_ms,
            'content': self.content,
            'meta': meta,
        }


    # Deserialization
    @classmethod
    def from_dict(cls, data):
        start_ms = data['start_ms']
        end_ms = data['end_ms']
        content = data['content']

        meta = data.get('meta', {})
        starts_paragraph = meta.get('starts_paragraph', False)

        return Subtitle(start_ms, end_ms, content, starts_paragraph)


class SubtitleSet(list):
    """A set of subtitles for a video.

    SubtitleSets may only contain Subtitle objects.  This will be sanity-checked
    for you when using the editing functions.

    They inherit from vanilla Python lists, so they should support most listy
    functionality like slicing, append, insert, pop, etc.

    It's up to you to keep them in order.  Good luck.

    """
    TYPE_ERROR =  "SubtitleSets may only contain Subtitle objects!"

    # Creation
    def __init__(self, subtitles=None):
        if subtitles:
            subtitles = list(subtitles)
        else:
            subtitles = []

        for subtitle in subtitles:
            assert isinstance(subtitle, Subtitle), SubtitleSet.TYPE_ERROR

        return super(SubtitleSet, self).__init__(subtitles)


    # I am now a human type system.
    def append(self, subtitle):
        assert isinstance(subtitle, Subtitle), SubtitleSet.TYPE_ERROR
        return super(SubtitleSet, self).append(subtitle)

    def prepend(self, subtitle):
        return self.insert(0, subtitle)

    def insert(self, index, subtitle):
        assert isinstance(subtitle, Subtitle), SubtitleSet.TYPE_ERROR
        return super(SubtitleSet, self).insert(index, subtitle)

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            for subtitle in value:
                assert isinstance(subtitle, Subtitle), SubtitleSet.TYPE_ERROR
        else:
            assert isinstance(value, Subtitle), SubtitleSet.TYPE_ERROR

        return super(SubtitleSet, self).__setitem__(key, value)


    # Serialization
    def to_list(self):
        return list(sub.to_dict() for sub in self)

    def to_json(self):
        return json.dumps(self.to_list())

    def to_zip(self):
        return zlib.compress(self.to_json())


    # Deserialization
    @classmethod
    def from_list(cls, data):
        subtitles = list(Subtitle.from_dict(sub) for sub in data)
        return SubtitleSet(subtitles=subtitles)

    @classmethod
    def from_json(cls, json_str):
        return SubtitleSet.from_list(json.loads(json_str))

    @classmethod
    def from_zip(cls, zip_data):
        return SubtitleSet.from_json(zlib.decompress(zip_data))


# Django Models ---------------------------------------------------------------
class SubtitleLanguage(models.Model):
    """SubtitleLanguages are the equivalent of a 'branch' in a VCS.

    These exist mostly to coordiante access to a language amongst users.  Most
    of the actual data for the subtitles is stored in the version themselves.

    """
    video = models.ForeignKey(Video, related_name='newsubtitlelanguage_set')
    language_code = models.CharField(max_length=16, choices=ALL_LANGUAGES)

    followers = models.ManyToManyField(User, blank=True,
                                       related_name='followed_newlanguages')
    collaborators = models.ManyToManyField(User, blank=True,
                                           related_name='collab_newlanguages')

    writelock_time = models.DateTimeField(null=True, blank=True,
                                          editable=False)
    writelock_owner = models.ForeignKey(User, null=True, blank=True,
                                        editable=False,
                                        related_name='writelocked_newlanguages')
    writelock_session_key = models.CharField(max_length=255, blank=True,
                                             editable=False)

    created = models.DateTimeField(editable=False)

    class Meta:
        unique_together = [('video', 'language_code')]


    def __unicode__(self):
        return 'SubtitleLanguage %s / %s / %s' % (
            (self.id or '(unsaved)'), self.video.video_id,
            self.get_language_code_display()
        )


    def save(self, *args, **kwargs):
        creating = not self.pk

        if creating:
            self.created = datetime.datetime.now()

        return super(SubtitleLanguage, self).save(*args, **kwargs)


    def get_tip(self):
        """Return the tipmost version of this language (if any)."""

        versions = self.subtitleversion_set.order_by('-version_number')[:1]

        if versions:
            return versions[0]
        else:
            return None


    def add_version(self, *args, **kwargs):
        """Add a SubtitleVersion to the tip of this language.

        You probably don't need this.  You probably want
        apps.subtitles.pipeline.add_subtitles instead.

        Does not check any writelocking -- that's up to the pipeline.

        """
        kwargs['subtitle_language'] = self
        kwargs['language_code'] = self.language_code
        kwargs['video'] = self.video

        tip = self.get_tip()

        version_number = ((tip.version_number + 1) if tip else 1)
        kwargs['version_number'] = version_number

        parents = kwargs.pop('parents', [])

        if tip:
            parents.append(tip)

        kwargs['lineage'] = get_lineage(parents)

        sv = SubtitleVersion(*args, **kwargs)
        sv.save()

        if parents:
            for p in parents:
                sv.parents.add(p)

        return sv


class SubtitleVersion(models.Model):
    """SubtitleVersions are the equivalent of a 'changeset' in a VCS.

    They are designed with a few key principles in mind.

    First, SubtitleVersions should be mostly immutable.  Once written they
    should never be changed, unless a team needs to publish or unpublish them.
    Any other changes should simply create a new version.

    Second, SubtitleVersions are self-contained.  There's a little bit of
    denormalization going on with the video and language_code fields, but this
    makes it much easier for a SubtitleVersion to stand on its own and will
    improve performance overall.

    Because they're (mostly) immutable, the denormalization is less of an issue
    than it would be otherwise.

    You should only create new SubtitleVersions through the `add_version` method
    of SubtitleLanguage instances.  This will ensure consistency and handle
    updating the parentage and version numbers correctly.

    """
    parents = models.ManyToManyField('self', symmetrical=False)

    video = models.ForeignKey(Video)
    subtitle_language = models.ForeignKey(SubtitleLanguage)
    language_code = models.CharField(max_length=16, choices=ALL_LANGUAGES)

    visibility = models.CharField(max_length=10,
                                  choices=(('public', 'public'),
                                           ('private', 'private')),
                                  default='public')

    version_number = models.PositiveIntegerField(default=0)

    author = models.ForeignKey(User, default=User.get_anonymous,
                               related_name='newsubtitleversion_set')

    title = models.CharField(max_length=2048, blank=True)
    description = models.TextField(blank=True)

    created = models.DateTimeField(editable=False)

    # Subtitles are stored in a text blob, serialized as JSON.  Use the
    # subtitles property to get and set them.  You shouldn't be touching this
    # field.
    serialized_subtitles = models.TextField(blank=True)

    # Lineage is stored as a blob of JSON to save on DB rows.  You shouldn't
    # need to touch this field yourself, use the lineage property.
    serialized_lineage = models.TextField(blank=True)


    def get_subtitles(self):
        # We cache the parsed subs for speed.
        if self._subtitles == None:
            self._subtitles = json_to_subtitles(self.serialized_subtitles)

        return self._subtitles

    def set_subtitles(self, subtitles):
        self.serialized_subtitles = subtitles_to_json(subtitles)
        self._subtitles = subtitles

    subtitles = property(get_subtitles, set_subtitles)

    def get_lineage(self):
        # We cache the parsed lineage for speed.
        if self._lineage == None:
            self._lineage = json_to_lineage(self.serialized_lineage)

        return self._lineage

    def set_lineage(self, lineage):
        self.serialized_lineage = lineage_to_json(lineage)
        self._lineage = lineage

    lineage = property(get_lineage, set_lineage)


    class Meta:
        unique_together = [('video', 'language_code', 'version_number')]


    def __init__(self, *args, **kwargs):
        subtitles = kwargs.pop('subtitles', None)
        lineage = kwargs.pop('lineage', None)

        super(SubtitleVersion, self).__init__(*args, **kwargs)

        self._subtitles = None
        if subtitles:
            self.subtitles = subtitles

        self._lineage = None
        if lineage != None:
            self.lineage = lineage

    def __unicode__(self):
        return u'SubtitleVersion %s / %s / %s v%s' % (
            (self.id or '(unsaved)'), self.video.video_id,
            self.get_language_code_display(), self.version_number
        )


    def save(self, *args, **kwargs):
        creating = not self.pk

        if creating:
            self.created = datetime.datetime.now()

        return super(SubtitleVersion, self).save(*args, **kwargs)


    def get_ancestors(self):
        """Return all ancestors of this version.  WARNING: MAY EAT YOUR DB!

        Returning all ancestors of a version is very database-intensive, because
        we need to walk each relation.  It will make roughly l^b database calls,
        where l is the length of a branch of history and b is the "branchiness".

        You probably don't need this.  You probably want to use the lineage
        instead.  This is mostly here for sanity tests.

        """
        def _ancestors(version):
            return [version] + list(mapcat(_ancestors, version.parents.all()))

        return set(mapcat(_ancestors, self.parents.all()))

