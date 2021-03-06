# -*- coding: utf-8 -*-
#       This program is free software; you can redistribute it and/or modify
#       it under the terms of the GNU General Public License as published by
#       the Free Software Foundation; either version 2 of the License, or
#       (at your option) any later version.
#       
#       This program is distributed in the hope that it will be useful,
#       but WITHOUT ANY WARRANTY; without even the implied warranty of
#       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#       GNU General Public License for more details.
#       
#       You should have received a copy of the GNU General Public License
#       along with this program; if not, write to the Free Software
#       Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#       MA 02110-1301, USA.
import json
from django import forms
from django_push.publisher import ping_hub
from tagging.models import Tag
from timezones.forms import TimeZoneField
from tagging_autocomplete.widgets import TagAutocomplete
from main.models import Comment, Post, Blog, UserInBlog, Notify, Draft, Answer
from django.conf import settings
from djang0parser import utils
from main.utils import ModelFormWithUser, PRETTY_TIMEZONE_CHOICES
from django.utils.translation import ugettext as _


class RegisterForm(forms.Form):
    """Registration form"""
    name = forms.CharField()
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)

class LoginForm(forms.Form):
    """Login form"""
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)
    save = forms.CheckboxInput()

class CreateBlogForm(ModelFormWithUser):
    """Create new blog form"""

    def save(self, commit=True):
        self.instance.owner = self.user
        inst = super(CreateBlogForm, self).save(commit)
        UserInBlog.objects.create(
            blog=inst,
            user=self.user,
        )
        return inst

    class Meta:
        model = Blog
        fields = ('description', 'name')


class BasePostForm(ModelFormWithUser):
    """Base post form"""

    def clean_blog(self):
        blog = self.cleaned_data.get('blog', None)
        if blog and not blog.check_user(self.user):
            raise forms.ValidationError(_('You not in this blog!'))
        return blog

    class Meta:
        model = Post
        fields = (
            'type', 'blog', 'addition',
            'title', 'text', 'raw_tags',
        )


class CreatePostForm(BasePostForm):
    """Create new post form"""

    def clean_text(self):
        text = self.cleaned_data.get('text', None)
        if not text:
            raise forms.ValidationError(_('This post type require text!'))
        return text

    def clean_addition(self):
        addition = self.cleaned_data.get('addition', None)
        if self.cleaned_data.get('type') in (Post.TYPE_LINK, Post.TYPE_TRANSLATE) and not addition:
            raise forms.ValidationError(_('This post type require addition!'))
        return addition

    def clean_type(self):
        _type = self.cleaned_data.get('type')
        if _type not in (Post.TYPE_POST, Post.TYPE_LINK, Post.TYPE_TRANSLATE):
            raise forms.ValidationError(_('Wrong post type!'))
        return _type

    def save(self, commit=True):
        inst = self.instance
        inst.author = self.user
        inst.preview, inst.text = utils.cut(inst.text)
        inst.preview = utils.parse(inst.preview, settings.VALID_TAGS, settings.VALID_ATTRS)
        inst.text = utils.parse(inst.text, settings.VALID_TAGS, settings.VALID_ATTRS)
        inst = super(CreatePostForm, self).save(commit)
        Tag.objects.update_tags(inst, inst.raw_tags)
        inst.create_comment_root()
        for mention in utils.find_mentions(inst.text):
            Notify.new_mention_notify(mention, post=inst)
        if settings.PUBSUB:
            ping_hub(settings.FEED_URL, hub_url=settings.PUSH_HUB)
        return inst


class CreateAnswerForm(BasePostForm):
    answers = forms.CharField(label=_('answers'))

    def clean_type(self):
        _type = self.cleaned_data.get('type')
        if _type not in (Post.TYPE_ANSWER, Post.TYPE_MULTIPLE_ANSWER):
            raise forms.ValidationError(_('Wrong type!'))
        return _type

    def clean_answers(self):
        answers = self.cleaned_data.get('answers')
        try:
            parsed = json.loads(answers)
        except ValueError:
            raise forms.ValidationError(_('answers broken'))
        if type(parsed) is not list:
            raise forms.ValidationError(_('answers broken'))
        if len(parsed) < 2:
            raise forms.ValidationError(_('too little answers'))
        return map(str, parsed)

    def save(self, commit=True):
        self.instance.author = self.user
        post = super(CreateAnswerForm, self).save(commit)
        for answer in self.cleaned_data.get('answers'):
            Answer.objects.create(
                post=post, value=answer,
            )
        Tag.objects.update_tags(post, post.raw_tags)
        post.create_comment_root()
        for mention in utils.find_mentions(post.text):
            Notify.new_mention_notify(mention, post=post)
        if settings.PUBSUB:
            ping_hub(settings.FEED_URL, hub_url=settings.PUSH_HUB)
        return post


class EditPostForm(ModelFormWithUser):

    def clean_blog(self):
        blog = self.cleaned_data.get('blog', None)
        if blog and not (
            blog.check_user(self.user) or
            blog.check_user(self.instance.author)
        ):
            raise forms.ValidationError(_('You not in this blog!'))
        return blog

    def clean_addition(self):
        addition = self.cleaned_data.get('addition', None)
        if self.cleaned_data.get('type') in (Post.TYPE_LINK, Post.TYPE_TRANSLATE) and not addition:
            raise forms.ValidationError(_('This post type require addition!'))
        return addition

    def clean(self):
        if self.instance.type in (Post.TYPE_ANSWER, Post.TYPE_MULTIPLE_ANSWER):
            raise forms.ValidationError(_('Edit this type not allowed!'))
        return self.cleaned_data

    def save(self, commit=True):
        self.instance.preview, self.instance.text = utils.cut(self.instance.text)
        self.instance.preview = utils.parse(self.instance.preview, settings.VALID_TAGS, settings.VALID_ATTRS)
        self.instance.text = utils.parse(self.instance.text, settings.VALID_TAGS, settings.VALID_ATTRS)
        return super(EditPostForm, self).save(commit)

    class Meta:
        model = Post
        fields = (
            'blog', 'text', 'title',
            'raw_tags', 'addition',
        )


class EditDraftForm(ModelFormWithUser):
    """Edit or create draft form"""

    def __init__(self, *args, **kwargs):
        super(EditDraftForm, self).__init__(*args, **kwargs)
        self.fields['title'].required = False
        if 'instance' in kwargs:
            self.fields['type'].required = False
            self.cached_type = kwargs['instance'].type
        else:
            self.cached_type = ''

    def clean_type(self):
        _type = self.cleaned_data.get('type', '')
        if _type == '':
            _type = self.cached_type
        if _type == '' or _type in (Post.TYPE_ANSWER, Post.TYPE_MULTIPLE_ANSWER):
            raise forms.ValidationError(_('Not allowed type!'))
        return _type

    def clean_title(self):
        return self.cleaned_data.get('title', _('Unnamed post'))

    def save(self, commit=True):
        self.instance.author = self.user
        return super(EditDraftForm, self).save(commit)

    class Meta:
        model = Draft
        fields = (
            'type', 'blog', 'addition',
            'title', 'text', 'raw_tags',
        )


class CreateCommentForm(forms.Form):
    """Create new comment form"""
    text = forms.CharField(widget=forms.Textarea)
    post = forms.IntegerField(widget=forms.HiddenInput)
    comment = forms.IntegerField(widget=forms.HiddenInput, required=False)

    def clean(self):
        """Clean and receive data"""
        data = self.cleaned_data
        try:
            data['post_obj'] = Post.objects.get(
                id=data['post'],
                disable_reply=False,
            )
        except Post.DoesNotExist:
            raise forms.ValidationError("Post not found")
        try:
            data['root'] = Comment.objects.select_related('author').get(
                id=data['comment'],
                post=data['post_obj'],
            )
        except Comment.DoesNotExist:
            data['root'] = Comment.objects.select_related('author').get(
                post=data['post_obj'],
                depth=1.
            )
        data['raw_text'] = data['text']
        data['text'] = utils.parse(data['text'], settings.VALID_TAGS, settings.VALID_ATTRS)
        return data
    
class EditUserForm(forms.Form):
    """Edit user settings form"""
    mail = forms.EmailField()
    show_mail = forms.BooleanField(required=False)
    icq = forms.CharField(required=False)
    jabber = forms.CharField(required=False)
    city = forms.CharField(required=False)
    timezone = TimeZoneField(required=False, choices=PRETTY_TIMEZONE_CHOICES)
    site = forms.URLField(required=False)
    about = forms.CharField(widget=forms.Textarea, required=False)
    notify_post_reply = forms.BooleanField(required=False)
    notify_comment_reply = forms.BooleanField(required=False)
    notify_pm = forms.BooleanField(required=False)
    notify_mention = forms.BooleanField(required=False)
    notify_spy = forms.BooleanField(required=False)


class PostOptions(forms.ModelForm):
    """Edit post settings"""

    class Meta:
        models = Post
        fields = ('disable_rate', 'disable_reply', 'pinch',)


class EditUserPick(forms.Form):
    userpic = forms.ImageField()

class SearchForm(forms.Form):
    """Search form"""
    query = forms.CharField()
