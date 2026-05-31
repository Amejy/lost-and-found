from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import DateField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length


CATEGORY_CHOICES = [
    ("Electronics", "Electronics"),
    ("Documents", "Documents"),
    ("Bags", "Bags"),
    ("Clothing", "Clothing"),
    ("Accessories", "Accessories"),
    ("Keys", "Keys"),
    ("Pets", "Pets"),
    ("Other", "Other"),
]


class BaseItemForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(min=3, max=150)])
    description = TextAreaField("Description", validators=[DataRequired(), Length(min=10, max=2000)])
    category = SelectField("Category", validators=[DataRequired()], choices=CATEGORY_CHOICES)
    location = StringField("Location", validators=[DataRequired(), Length(min=3, max=150)])
    image = FileField(
        "Image",
        validators=[FileAllowed(["jpg", "jpeg", "png", "webp"], "Images only.")],
    )


class LostItemForm(BaseItemForm):
    date_lost = DateField("Date lost", validators=[DataRequired()], format="%Y-%m-%d")
    submit = SubmitField("Submit lost item")


class FoundItemForm(BaseItemForm):
    date_found = DateField("Date found", validators=[DataRequired()], format="%Y-%m-%d")
    submit = SubmitField("Submit found item")
