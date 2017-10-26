import datetime

import pytest
from unittest.mock import Mock
from django.db import models
from django.utils.functional import SimpleLazyObject
from py.test import raises

import graphene
from graphene.relay import Node

from ..utils import DJANGO_FILTER_INSTALLED
from ..compat import MissingType, JSONField
from ..fields import DjangoConnectionField
from ..types import DjangoObjectType
from ..settings import graphene_settings
from .models import Article, Reporter
from ..auth.decorators import node_require_permission

pytestmark = pytest.mark.django_db


class MockUserContext(object):

    def __init__(self, authenticated=True, is_staff=False, superuser=False, perms=()):
        self.user = self
        self.authenticated = authenticated
        self.is_staff = is_staff
        self.is_superuser = superuser
        self.perms = perms

    def is_authenticated(self):
        return self.authenticated

    def has_perm(self, check_perms):
        print("FUCK", check_perms not in self.perms)
        if check_perms not in self.perms:
            print("NO PERMS")
            return False
        print("HAS PERMS")
        return True


class Context(object):

    def __init__(self, user):
        self.user = user


class Request(object):

    def __init__(self, user):
        self.context = Context(user)


user_authenticated = MockUserContext(authenticated=True, perms=('can_view_foo',))
user_anonymous = MockUserContext(authenticated=False)
user_with_permissions = MockUserContext(authenticated=True, perms=('can_view_foo', 'can_view_bar'))


def test_anonymous_user():
    class ReporterType(DjangoObjectType):

        class Meta:
            model = Reporter
            interfaces = (Node, )
            only_fields = ('id', )

        @classmethod
        @node_require_permission(permissions=('can_view_foo', ))
        def get_node(cls, info, id):
            return super(ReporterType, cls).get_node(info, id)

    class Query(graphene.ObjectType):
        reporter = graphene.Field(ReporterType)

        def resolve_reporter(self, info):
            print("THIS IS INFO----", info.context)
            print("THIS IS INFO----", info.context is None)
            print("User----", info.context.user.authenticated is True)
            return SimpleLazyObject(lambda: Reporter(id=1))

    schema = graphene.Schema(query=Query)
    query = '''
        query {
          reporter {
            id
          }
        }
    '''
    request = Context(user=user_anonymous)
    result = schema.execute(query, context_value=request)
    ReporterType.get_node(request, 1)
    assert not result.errors
    assert result.data == {
        'reporter': {
            'id': 'UmVwb3J0ZXJUeXBlOjE='
        }
    }


def test_user_authenticated():
    class ReporterType(DjangoObjectType):

        class Meta:
            model = Reporter
            interfaces = (Node, )

        @node_require_permission(permissions=('can_view_foo', ))
        def get_node(self, info, id):
            1/0
            print("THIS SHIT IS CALLED")
            return super(ReporterType, self).get_node(self, info, id)

    class Query(graphene.ObjectType):
        reporter = graphene.Field(ReporterType)

        def resolve_reporter(self, info):
            return Reporter(first_name='ABA', last_name='X')

    query = '''
        query ReporterQuery {
          reporter {
            firstName,
            lastName,
            email
          }
        }
    '''
    expected = {
        'reporter': {
            'firstName': 'ABA',
            'lastName': 'X',
            'email': ''
        }
    }
    schema = graphene.Schema(query=Query)
    request = Context(user=user_anonymous)
    result = schema.execute(query, context_value=request)
    assert not result.errors
    assert result.data == expected


@pytest.mark.skipif(JSONField is MissingType,
                    reason="RangeField should exist")
def test_should_query_postgres_fields():
    from django.contrib.postgres.fields import IntegerRangeField, ArrayField, JSONField, HStoreField

    class Event(models.Model):
        ages = IntegerRangeField(help_text='The age ranges')
        data = JSONField(help_text='Data')
        store = HStoreField()
        tags = ArrayField(models.CharField(max_length=50))

    class EventType(DjangoObjectType):

        class Meta:
            model = Event

    class Query(graphene.ObjectType):
        event = graphene.Field(EventType)

        def resolve_event(self, info):
            return Event(
                ages=(0, 10),
                data={'angry_babies': True},
                store={'h': 'store'},
                tags=['child', 'angry', 'babies']
            )

    schema = graphene.Schema(query=Query)
    query = '''
        query myQuery {
          event {
            ages
            tags
            data
            store
          }
        }
    '''
    expected = {
        'event': {
            'ages': [0, 10],
            'tags': ['child', 'angry', 'babies'],
            'data': '{"angry_babies": true}',
            'store': '{"h": "store"}',
        },
    }
    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_node():
    # reset_global_registry()
    # Node._meta.registry = get_global_registry()

    class ReporterNode(DjangoObjectType):

        class Meta:
            model = Reporter
            interfaces = (Node, )

        @classmethod
        def get_node(cls, info, id):
            return Reporter(id=2, first_name='Cookie Monster')

        def resolve_articles(self, info, **args):
            return [Article(headline='Hi!')]

    class ArticleNode(DjangoObjectType):

        class Meta:
            model = Article
            interfaces = (Node, )

        @classmethod
        def get_node(cls, info, id):
            return Article(id=1, headline='Article node', pub_date=datetime.date(2002, 3, 11))

    class Query(graphene.ObjectType):
        node = Node.Field()
        reporter = graphene.Field(ReporterNode)
        article = graphene.Field(ArticleNode)

        def resolve_reporter(self, info):
            return Reporter(id=1, first_name='ABA', last_name='X')

    query = '''
        query ReporterQuery {
          reporter {
            id,
            firstName,
            articles {
              edges {
                node {
                  headline
                }
              }
            }
            lastName,
            email
          }
          myArticle: node(id:"QXJ0aWNsZU5vZGU6MQ==") {
            id
            ... on ReporterNode {
                firstName
            }
            ... on ArticleNode {
                headline
                pubDate
            }
          }
        }
    '''
    expected = {
        'reporter': {
            'id': 'UmVwb3J0ZXJOb2RlOjE=',
            'firstName': 'ABA',
            'lastName': 'X',
            'email': '',
            'articles': {
                'edges': [{
                  'node': {
                      'headline': 'Hi!'
                  }
                }]
            },
        },
        'myArticle': {
            'id': 'QXJ0aWNsZU5vZGU6MQ==',
            'headline': 'Article node',
            'pubDate': '2002-03-11',
        }
    }
    schema = graphene.Schema(query=Query)
    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_query_connectionfields():
    class ReporterType(DjangoObjectType):

        class Meta:
            model = Reporter
            interfaces = (Node, )
            only_fields = ('articles', )

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

        def resolve_all_reporters(self, info, **args):
            return [Reporter(id=1)]

    schema = graphene.Schema(query=Query)
    query = '''
        query ReporterConnectionQuery {
          allReporters {
            pageInfo {
              hasNextPage
            }
            edges {
              node {
                id
              }
            }
          }
        }
    '''
    result = schema.execute(query)
    assert not result.errors
    assert result.data == {
        'allReporters': {
            'pageInfo': {
                'hasNextPage': False,
            },
            'edges': [{
                'node': {
                    'id': 'UmVwb3J0ZXJUeXBlOjE='
                }
            }]
        }
    }


def test_should_keep_annotations():
    from django.db.models import (
        Count,
        Avg,
    )

    class ReporterType(DjangoObjectType):

        class Meta:
            model = Reporter
            interfaces = (Node, )
            only_fields = ('articles', )

    class ArticleType(DjangoObjectType):

        class Meta:
            model = Article
            interfaces = (Node, )
            filter_fields = ('lang', )

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)
        all_articles = DjangoConnectionField(ArticleType)

        def resolve_all_reporters(self, info, **args):
            return Reporter.objects.annotate(articles_c=Count('articles')).order_by('articles_c')

        def resolve_all_articles(self, info, **args):
            return Article.objects.annotate(import_avg=Avg('importance')).order_by('import_avg')

    schema = graphene.Schema(query=Query)
    query = '''
        query ReporterConnectionQuery {
          allReporters {
            pageInfo {
              hasNextPage
            }
            edges {
              node {
                id
              }
            }
          }
          allArticles {
            pageInfo {
              hasNextPage
            }
            edges {
              node {
                id
              }
            }
          }
        }
    '''
    result = schema.execute(query)
    assert not result.errors


@pytest.mark.skipif(not DJANGO_FILTER_INSTALLED,
                    reason="django-filter should be installed")
def test_should_query_node_filtering():
    class ReporterType(DjangoObjectType):

        class Meta:
            model = Reporter
            interfaces = (Node, )

    class ArticleType(DjangoObjectType):

        class Meta:
            model = Article
            interfaces = (Node, )
            filter_fields = ('lang', )

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

    r = Reporter.objects.create(
        first_name='John',
        last_name='Doe',
        email='johndoe@example.com',
        a_choice=1
    )
    Article.objects.create(
        headline='Article Node 1',
        pub_date=datetime.date.today(),
        reporter=r,
        editor=r,
        lang='es'
    )
    Article.objects.create(
        headline='Article Node 2',
        pub_date=datetime.date.today(),
        reporter=r,
        editor=r,
        lang='en'
    )

    schema = graphene.Schema(query=Query)
    query = '''
        query NodeFilteringQuery {
            allReporters {
                edges {
                    node {
                        id
                        articles(lang: "es") {
                            edges {
                                node {
                                    id
                                }
                            }
                        }
                    }
                }
            }
        }
    '''

    expected = {
        'allReporters': {
            'edges': [{
                'node': {
                    'id': 'UmVwb3J0ZXJUeXBlOjE=',
                    'articles': {
                        'edges': [{
                            'node': {
                                'id': 'QXJ0aWNsZVR5cGU6MQ=='
                            }
                        }]
                    }
                }
            }]
        }
    }

    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


@pytest.mark.skipif(not DJANGO_FILTER_INSTALLED,
                    reason="django-filter should be installed")
def test_should_query_node_multiple_filtering():
    class ReporterType(DjangoObjectType):

        class Meta:
            model = Reporter
            interfaces = (Node, )

    class ArticleType(DjangoObjectType):

        class Meta:
            model = Article
            interfaces = (Node, )
            filter_fields = ('lang', 'headline')

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

    r = Reporter.objects.create(
        first_name='John',
        last_name='Doe',
        email='johndoe@example.com',
        a_choice=1
    )
    Article.objects.create(
        headline='Article Node 1',
        pub_date=datetime.date.today(),
        reporter=r,
        editor=r,
        lang='es'
    )
    Article.objects.create(
        headline='Article Node 2',
        pub_date=datetime.date.today(),
        reporter=r,
        editor=r,
        lang='es'
    )
    Article.objects.create(
        headline='Article Node 3',
        pub_date=datetime.date.today(),
        reporter=r,
        editor=r,
        lang='en'
    )

    schema = graphene.Schema(query=Query)
    query = '''
        query NodeFilteringQuery {
            allReporters {
                edges {
                    node {
                        id
                        articles(lang: "es", headline: "Article Node 1") {
                            edges {
                                node {
                                    id
                                }
                            }
                        }
                    }
                }
            }
        }
    '''

    expected = {
        'allReporters': {
            'edges': [{
                'node': {
                    'id': 'UmVwb3J0ZXJUeXBlOjE=',
                    'articles': {
                        'edges': [{
                            'node': {
                                'id': 'QXJ0aWNsZVR5cGU6MQ=='
                            }
                        }]
                    }
                }
            }]
        }
    }

    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_enforce_first_or_last():
    graphene_settings.RELAY_CONNECTION_ENFORCE_FIRST_OR_LAST = True

    class ReporterType(DjangoObjectType):

        class Meta:
            model = Reporter
            interfaces = (Node, )

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

    r = Reporter.objects.create(
        first_name='John',
        last_name='Doe',
        email='johndoe@example.com',
        a_choice=1
    )

    schema = graphene.Schema(query=Query)
    query = '''
        query NodeFilteringQuery {
            allReporters {
                edges {
                    node {
                        id
                    }
                }
            }
        }
    '''

    expected = {
        'allReporters': None
    }

    result = schema.execute(query)
    assert len(result.errors) == 1
    assert str(result.errors[0]) == (
        'You must provide a `first` or `last` value to properly '
        'paginate the `allReporters` connection.'
    )
    assert result.data == expected


def test_should_error_if_first_is_greater_than_max():
    graphene_settings.RELAY_CONNECTION_MAX_LIMIT = 100

    class ReporterType(DjangoObjectType):

        class Meta:
            model = Reporter
            interfaces = (Node, )

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

    r = Reporter.objects.create(
        first_name='John',
        last_name='Doe',
        email='johndoe@example.com',
        a_choice=1
    )

    schema = graphene.Schema(query=Query)
    query = '''
        query NodeFilteringQuery {
            allReporters(first: 101) {
                edges {
                    node {
                        id
                    }
                }
            }
        }
    '''

    expected = {
        'allReporters': None
    }

    result = schema.execute(query)
    assert len(result.errors) == 1
    assert str(result.errors[0]) == (
        'Requesting 101 records on the `allReporters` connection '
        'exceeds the `first` limit of 100 records.'
    )
    assert result.data == expected

    graphene_settings.RELAY_CONNECTION_ENFORCE_FIRST_OR_LAST = False


def test_should_query_promise_connectionfields():
    from promise import Promise

    class ReporterType(DjangoObjectType):

        class Meta:
            model = Reporter
            interfaces = (Node, )

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

        def resolve_all_reporters(self, info, **args):
            return Promise.resolve([Reporter(id=1)])

    schema = graphene.Schema(query=Query)
    query = '''
        query ReporterPromiseConnectionQuery {
            allReporters(first: 1) {
                edges {
                    node {
                        id
                    }
                }
            }
        }
    '''

    expected = {
        'allReporters': {
            'edges': [{
                'node': {
                    'id': 'UmVwb3J0ZXJUeXBlOjE='
                }
            }]
        }
    }

    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_query_dataloader_fields():
    from promise import Promise
    from promise.dataloader import DataLoader

    def article_batch_load_fn(keys):
        queryset = Article.objects.filter(reporter_id__in=keys)
        return Promise.resolve([
            [article for article in queryset if article.reporter_id == id]
            for id in keys
        ])

    article_loader = DataLoader(article_batch_load_fn)

    class ArticleType(DjangoObjectType):

        class Meta:
            model = Article
            interfaces = (Node, )

    class ReporterType(DjangoObjectType):

        class Meta:
            model = Reporter
            interfaces = (Node, )
            use_connection = True

        articles = DjangoConnectionField(ArticleType)

        def resolve_articles(self, info, **args):
            return article_loader.load(self.id)

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

    r = Reporter.objects.create(
        first_name='John',
        last_name='Doe',
        email='johndoe@example.com',
        a_choice=1
    )
    Article.objects.create(
        headline='Article Node 1',
        pub_date=datetime.date.today(),
        reporter=r,
        editor=r,
        lang='es'
    )
    Article.objects.create(
        headline='Article Node 2',
        pub_date=datetime.date.today(),
        reporter=r,
        editor=r,
        lang='en'
    )

    schema = graphene.Schema(query=Query)
    query = '''
        query ReporterPromiseConnectionQuery {
            allReporters(first: 1) {
                edges {
                    node {
                        id
                        articles(first: 2) {
                            edges {
                                node {
                                    headline
                                }
                            }
                        }
                    }
                }
            }
        }
    '''

    expected = {
        'allReporters': {
            'edges': [{
                'node': {
                    'id': 'UmVwb3J0ZXJUeXBlOjE=',
                    'articles': {
                        'edges': [{
                            'node': {
                                'headline': 'Article Node 1',
                            }
                        }, {
                            'node': {
                                'headline': 'Article Node 2'
                            }
                        }]
                    }
                }
            }]
        }
    }

    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected