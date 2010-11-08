# -*- coding: utf-8 -*-
from djang0byte.main.forms import CreateCommentForm
from django.db import transaction
from django.contrib import auth
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render_to_response
from main.forms import CreatePostForm, CreateCommentForm
from main.models import *
from django.views.decorators.cache import cache_page
from simplepagination import paginate
from annoying.decorators import render_to

@transaction.commit_on_success
@login_required
def newpost(request, type = 'post'):
    """Create post form and action"""
    profile = request.user.get_profile()
    if type == 'post':
      if request.method == 'POST':
	  form = CreatePostForm(request.POST)
	  if form.is_valid():
	      data = form.cleaned_data
	      post = Post()
	      post.author = request.user
	      post.setBlog(request.POST.get('blog'))
	      post.title = data['title']
	      post.setText(data['text'])
	      post.owner = request.user
	      post.type = 0#'Post'
	      post.save()
	      post.setTags(data['tags'])
	      post.createCommentRoot()
	      #comment_root = Comment.add_root(post=post, created=datetime.datetime.now())
	      #comment_root.save()
	      return HttpResponseRedirect('/post/%d/' % (post.id))
      else:
          form = CreatePostForm()
      return render_to_response('newpost.html', {'form': form, 'blogs': profile.getBlogs()})
    else:
      if request.method == 'POST':
        post = Post()
        post.title = request.POST.get('title')
        post.author = request.user
        post.setBlog(request.POST.get('blog'))
	if request.POST.get('multi', 0):
	  post.type = 4#'Multiple Answer'
	else:
	  post.type = 3#post.type = 'Answer'
	post.save()
	post.setTags(request.POST.get('tags'))
	post.createCommentRoot()
	for answer_item in range(int(request.POST.get('count'))):
	  answer = Answer()
	  answer.value = request.POST.get(str(answer_item))
	  answer.post = post
	  answer.save()
	return HttpResponseRedirect('/post/%d/' % (post.id))
      multi = False
      count = 2
      return render_to_response('newanswer.html', {'answers_count': range(count),
	'count': count, 'blogs': profile.getBlogs(), 'multi': multi})

@cache_page(0)  
def post(request, id):
    """Print single post"""
    post = Post.objects.get(id=id)
    author = post.author.get_profile()
    comments = post.getComment()
    form = CreateCommentForm({'post': id, 'comment': 0})
    if post.type in (3, 4):
        is_answer = True
        answer = Answer.objects.filter(post=post)
        if request.user.is_authenticated() and Answer.check(post, request.user):
            result = False
        else:
            result = True
    else:
        is_answer = False
        result = False
        answer= None
        post.getContent = post.getFullContent
    return render_to_response('post.html', 
        {'post': post, 'author': author, 'comments': comments, 'comment_form': form,
        'is_answer': is_answer, 'result': result, 'answer': answer}
        )

@cache_page(0)  
@render_to('post_list.html')
@paginate(style='digg', per_page=10)   
def post_list(request, type = None, param = None):
    """Print post list"""
    posts = None
    if type == None:
        posts = Post.objects.all()
    elif type == 'pers':
        posts = Post.objects.filter(blog=None)
    elif type == 'main':
		posts = Post.objects.exclude(blog=None)
    elif type == 'blog':
        blog = Blog.objects.filter(id=param)[0]
        posts = blog.getPosts()
    elif type == 'tag':
        tag = Tag.objects.get(name=param)
        posts_with_tag = tag.getPosts()
        posts = []
        for post in posts_with_tag:
	  posts.append(post.post)
    elif type == 'auth':
        user = User.objects.filter(username=param)[0]
        profile = user.get_profile()
        posts = profile.getPosts()
    elif type == 'favourite':
        favourites = Favourite.objects.filter(user=request.user)
        posts = []
        for post in favourites:
            posts.append(post.post)
        
    return {'object_list': posts}

def post_list_with_param(request, type, param = None):
    """Wrapper for post_list"""
    return post_list(request, type, param)

@login_required
def new_comment(request, post = 0, comment = 0):
    """New comment form"""
    if request.method == 'POST':
        form = CreateCommentForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            post = Post.objects.get(id=data['post'])
            if data['comment'] == 0:
                root = Comment.objects.get(post=post, depth=1)
            else:
                root = Comment.objects.get(id=data['comment'])

            comment = root.add_child(post=post,
            author=request.user, text=data['text'],
            created=datetime.datetime.now())
            comment.save()
            return HttpResponseRedirect('/post/%d/#cmnt%d' %
                            (comment.post.id, comment.id))
    else:
        form = CreateCommentForm({'post': post, 'comment': comment})
    return render_to_response('new_comment.html', {'form': form})
        
	    
@login_required
def action(request, type, id, action = None):
    """Add or remove from favourite and spy, rate"""
    post = Post.objects.get(id=id)
    if type == 'favourite':
        try:
            favourite = Favourite.objects.get(post=post, user=request.user)
            favourite.delete()
        except Favourite.DoesNotExist:
            favourite = Favourite()
            favourite.post = post
            favourite.user = request.user
            favourite.save()
    elif type == 'spy':
        spy = Spy.object.get(post=post, user=request.user)
        if spy:
            spy.delete()
        else:
            spy.post = post
            spy.user = request.user
            spy.save()
    elif type == 'rate' and request.user != post.author:
        if action == '1':
          post.ratePost(request.user, +1)
        elif action == '0':
          post.ratePost(request.user, -1)
    elif type == 'answer':
        answers = Answer.objects.filter(post=post)
        if post.type == 3:
            answers.get(id=request.POST.get('answ')).vote(request.user)
        elif post.type == 4:
            for answer in answers:
                if request.POST.get('answ_' + str(answer.id), 0):
                    answer.vote(request.user, True)
            answer.fix(request.user)
    return HttpResponseRedirect('/post/%d/' % (int(id)))
