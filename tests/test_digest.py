import unittest
from unittest.mock import patch
import emailer
from sources.base import Dog


class DigestTests(unittest.TestCase):
    def dog(self, **kw):
        values = dict(id='test:1', name='Maple <3', source='test',
                      source_label='Rescue & Friends', url='https://example.org/dog',
                      description='Maple enjoys walks. She needs help with alone time.',
                      age='3 years', weight='20 lbs')
        values.update(kw)
        return Dog(**values)

    def test_story_keeps_qualifications_and_plain_text(self):
        dog = self.dog()
        self.assertEqual(emailer._digest_story(dog), dog.description)
        self.assertIn(dog.description, emailer.build_digest_text([dog], city='LA'))

    def test_missing_description_and_photo_still_has_card(self):
        dog = self.dog(description='')
        body = emailer.build_html([dog], city='LA', unsubscribe_for='test@example.org')
        self.assertIn('Meet Maple &lt;3 through Rescue &amp; Friends', body)
        self.assertIn('See all the dogs in LA', body)
        self.assertIn('Unsubscribe', body)
        self.assertNotIn('src=""', body)
        self.assertEqual(body.count('alt="LUVD"'), 2)

    def test_large_digest_bounded_and_all_dogs_in_text(self):
        dogs = [self.dog(name='Dog%s' % i) for i in range(100)]
        body = emailer.build_html(dogs, city='NYC')
        self.assertEqual(body.count('border-radius:15px'), 3)
        self.assertIn('Plus 85 more', body)
        self.assertLess(len(body.encode()), 100000)
        self.assertIn('Dog99', emailer.build_digest_text(dogs, city='NYC'))

    def test_program_details_and_tracking_preserved(self):
        dog = self.dog(program_label='Foster-to-adopt', program_note='Still in South Korea.')
        with patch.object(emailer, '_dog_link', return_value='https://luvd.com/e/9?d=test') as link:
            body = emailer.build_html([dog], city='NYC', send_id=9)
        link.assert_called_with(dog, 9)
        self.assertIn('Still in South Korea.', body)
        self.assertIn('https://luvd.com/e/9?d=test', body)

    def test_excerpt_is_bounded_and_html_escaped(self):
        dog = self.dog(description='<b>Hello & welcome.</b> ' + 'Long rescue description. ' * 100)
        story = emailer._digest_story(dog)
        self.assertLessEqual(len(story.split()), 65)
        self.assertNotIn('<b>', story)
        self.assertIn('Hello &amp; welcome.', emailer.build_html([dog]))
