from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SelectField, BooleanField
from wtforms.validators import DataRequired, Email, Length, Optional


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Keep me signed in")


class PostForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=250)])
    slug = StringField("URL slug", validators=[Optional(), Length(max=280)])
    excerpt = TextAreaField("Excerpt", validators=[Optional(), Length(max=400)])
    content_html = TextAreaField("Content", validators=[DataRequired()])
    category_id = SelectField("Category", coerce=int, validators=[Optional()])
    status = SelectField(
        "Status",
        choices=[("draft", "Draft"), ("scheduled", "Scheduled"), ("published", "Published")],
        default="draft",
    )
    meta_title = StringField("SEO title", validators=[Optional(), Length(max=70)])
    meta_description = TextAreaField("SEO description", validators=[Optional(), Length(max=160)])
    meta_keywords = StringField("SEO keywords", validators=[Optional(), Length(max=300)])


class ContactForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    phone = StringField("Phone", validators=[Optional(), Length(max=30)])
    subject = StringField("Subject", validators=[Optional(), Length(max=200)])
    message = TextAreaField("Message", validators=[DataRequired()])
